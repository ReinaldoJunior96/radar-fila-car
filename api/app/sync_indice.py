"""Sincronização controlada do índice do Radar.

Exemplos:
    python -m app.sync_indice --uf MA --municipio "Itapecuru Mirim"
    python -m app.sync_indice --uf MA --carga
    python -m app.sync_indice --uf MA --diario
    python -m app.sync_indice --uf MA --conferir
    python -m app.sync_indice --uf MA --loop
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

import psycopg

from . import indice, sicar
from .fonte import (
    CHANGE_PAGE_SIZE, FonteBloqueada, FonteCar, FonteIndisponivel, Municipio,
    OrcamentoEsgotado, ServicosPublicosCar,
)

ORCAMENTO_DIARIO = int(os.environ.get("SYNC_ORCAMENTO_DIARIO", "600"))
INTERVALO = float(os.environ.get("SYNC_INTERVALO_SEGUNDOS", "10"))
JANELA_INICIO = int(os.environ.get("SYNC_JANELA_INICIO", "20"))
JANELA_FIM_MINUTOS = int(os.environ.get("SYNC_JANELA_FIM_MINUTOS", "30"))
LIMITE_ALTERACOES = int(os.environ.get("SYNC_LIMITE_ALTERACOES", "5000"))
ORCAMENTO_MB_DIARIO = float(os.environ.get("SYNC_ORCAMENTO_MB_DIARIO", "300"))
LOTE_GEOMETRIAS = 200
MAX_FALHAS = 3
Conexao = psycopg.Connection[Any]


class RotinaPausada(Exception):
    pass


def agora_brasilia() -> datetime:
    return datetime.now(sicar.BRASILIA)


def dentro_da_janela(momento: datetime | None = None) -> bool:
    momento = momento or agora_brasilia()
    minutos = momento.hour * 60 + momento.minute
    return minutos >= JANELA_INICIO * 60 or minutos < JANELA_FIM_MINUTOS


def chamadas_de_hoje(conn: Conexao) -> int:
    inicio = agora_brasilia().replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        "SELECT coalesce(sum(chamadas), 0) FROM sync_execucao WHERE iniciado_em >= %s", (inicio,)
    ).fetchone()
    return int(row[0])


def bytes_de_hoje(conn: Conexao) -> int:
    inicio = agora_brasilia().replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        "SELECT coalesce(sum(bytes), 0) FROM sync_execucao WHERE iniciado_em >= %s", (inicio,)
    ).fetchone()
    return int(row[0])


def garantir_estado(conn: Conexao, uf: str) -> None:
    conn.execute("INSERT INTO sync_estado (uf) VALUES (%s) ON CONFLICT DO NOTHING", (uf,))


def verificar_pausa(conn: Conexao, uf: str) -> None:
    row = conn.execute(
        "SELECT pausado_ate, motivo_pausa FROM sync_estado WHERE uf = %s AND pausado_ate > now()", (uf,)
    ).fetchone()
    if row:
        raise RotinaPausada(f"Sincronização pausada até {row[0].isoformat()}: {row[1]}")


def pausar(conn: Conexao, uf: str, horas: int, motivo: str) -> None:
    conn.execute(
        """UPDATE sync_estado SET pausado_ate = now() + make_interval(hours => %s), motivo_pausa = %s
           WHERE uf = %s""",
        (horas, motivo[:500], uf),
    )


def marcar_estado(conn: Conexao, uf: str, **campos: Any) -> None:
    permitidos = {
        "carga_concluida_em", "marca", "ultimo_diario", "ultima_conferencia",
        "indicadores_em", "retificacoes_em", "geometrias_em",
    }
    assert set(campos) <= permitidos
    assignments = ", ".join(f"{campo} = %({campo})s" for campo in campos)
    conn.execute(f"UPDATE sync_estado SET {assignments} WHERE uf = %(uf)s", {**campos, "uf": uf})


@contextmanager
def trava_uf(conn: Conexao, uf: str) -> Iterator[bool]:
    row = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"sync:{uf}",)).fetchone()
    try:
        yield bool(row[0])
    finally:
        if row[0]:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"sync:{uf}",))


class Execucao:
    """Registra custo e resultado de uma tarefa, mesmo quando ela é interrompida."""

    def __init__(self, conn: Conexao, fonte: FonteCar, tipo: str, uf: str, detalhe: str | None = None) -> None:
        self.conn, self.fonte, self.tipo, self.uf, self.detalhe = conn, fonte, tipo, uf, detalhe
        self.totais = {"registros": 0, "novos": 0, "alterados": 0, "removidos": 0}
        self.base_chamadas = fonte.chamadas
        self.base_bytes = fonte.bytes_recebidos
        self.falhas = 0
        row = conn.execute(
            "INSERT INTO sync_execucao (tipo, uf, detalhe) VALUES (%s, %s, %s) RETURNING id",
            (tipo, uf, detalhe),
        ).fetchone()
        self.id = row[0]

    def somar(self, valores: dict[str, int]) -> None:
        for chave, valor in valores.items():
            self.totais[chave] += valor

    def salvar(self, status: str = "em_andamento", erro: str | None = None) -> dict[str, Any]:
        chamadas = self.fonte.chamadas - self.base_chamadas
        recebidos = self.fonte.bytes_recebidos - self.base_bytes
        fim = "clock_timestamp()" if status != "em_andamento" else "NULL"
        self.conn.execute(
            f"""UPDATE sync_execucao SET status = %s, erro = %s, chamadas = %s, bytes = %s,
                  registros = %s, novos = %s, alterados = %s, removidos = %s, terminado_em = {fim}
                WHERE id = %s""",
            (
                status, erro, chamadas, recebidos, self.totais["registros"], self.totais["novos"],
                self.totais["alterados"], self.totais["removidos"], self.id,
            ),
        )
        return {"tipo": self.tipo, "status": status, "chamadas": chamadas, "bytes": recebidos, **self.totais, "erro": erro}


def executar(
    conn: Conexao, fonte: FonteCar, tipo: str, uf: str, detalhe: str | None, tarefa: Callable[[Execucao], None]
) -> dict[str, Any]:
    garantir_estado(conn, uf)
    verificar_pausa(conn, uf)
    conn.commit()
    execucao = Execucao(conn, fonte, tipo, uf, detalhe)
    conn.commit()
    try:
        tarefa(execucao)
        resultado = execucao.salvar("concluida")
    except OrcamentoEsgotado as exc:
        conn.rollback()
        resultado = execucao.salvar("orcamento_esgotado", str(exc))
    except FonteBloqueada as exc:
        conn.rollback()
        pausar(conn, uf, 24, str(exc))
        resultado = execucao.salvar("bloqueada", str(exc))
    except FonteIndisponivel as exc:
        conn.rollback()
        pausar(conn, uf, 1, str(exc))
        resultado = execucao.salvar("falhou", str(exc))
    except SystemExit as exc:
        conn.rollback()
        execucao.salvar("falhou", str(exc))
        conn.commit()
        raise
    conn.commit()
    return resultado


def _obter_municipios(conn: Conexao, fonte: FonteCar, uf: str) -> list[Municipio]:
    rows = conn.execute(
        "SELECT ibge, nome, lon, lat FROM municipio_ref WHERE uf = %s ORDER BY nome", (uf,)
    ).fetchall()
    if rows:
        return [Municipio(*row) for row in rows]
    itens = fonte.municipios(uf)
    indice.gravar_municipios(conn, uf, itens)
    conn.commit()
    return itens


def _com_tolerancia(execucao: Execucao, acao: Callable[[], Any]) -> Any:
    """Tolera falhas isoladas e interrompe ao atingir falhas seguidas."""
    while True:
        try:
            valor = acao()
            execucao.falhas = 0
            return valor
        except FonteIndisponivel:
            execucao.falhas += 1
            if execucao.falhas >= MAX_FALHAS:
                raise
            time.sleep(0 if os.environ.get("SYNC_SEM_ESPERA") else 30 * execucao.falhas)


def carregar_municipios(
    conn: Conexao, fonte: FonteCar, uf: str, ciclo: str, nome: str | None = None
) -> dict[str, Any]:
    def tarefa(execucao: Execucao) -> None:
        municipios = _obter_municipios(conn, fonte, uf)
        if nome:
            alvo = sicar.plain(nome)
            municipios = [item for item in municipios if sicar.plain(item.nome) == alvo]
            if not municipios:
                raise SystemExit(f"Município não encontrado em {uf}: {nome}")
        feitos = {
            row[0]
            for row in conn.execute(
                "SELECT chave FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
            ).fetchall()
        }
        for municipio in municipios:
            chave = str(municipio.ibge)
            if chave in feitos:
                continue
            itens = _com_tolerancia(execucao, lambda: fonte.cadastro_municipio(uf, municipio.ibge))
            execucao.somar(
                indice.gravar_cadastro(conn, itens, (uf, municipio.ibge), historico=ciclo not in {"carga", "piloto"})
            )
            conn.execute(
                """INSERT INTO sync_checkpoint (uf, ciclo, chave) VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (uf, ciclo, chave),
            )
            execucao.salvar()
            conn.commit()
        if not nome:
            pendentes = {str(item.ibge) for item in municipios} - {
                row[0]
                for row in conn.execute(
                    "SELECT chave FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
                ).fetchall()
            }
            if not pendentes and ciclo == "carga":
                marcar_estado(conn, uf, carga_concluida_em=datetime.now(timezone.utc), marca=date.today())
                # A carga recém-concluída já vale como recarga do mês.
                conn.execute(
                    """INSERT INTO sync_checkpoint (uf, ciclo, chave)
                       SELECT uf, %s, ibge::text FROM municipio_ref WHERE uf = %s
                       ON CONFLICT DO NOTHING""",
                    (f"recarga:{date.today():%Y-%m}", uf),
                )

    return executar(conn, fonte, "carga", uf, nome or ciclo, tarefa)


def atualizar_indicadores(conn: Conexao, fonte: FonteCar, uf: str, nome: str | None = None) -> dict[str, Any]:
    def tarefa(execucao: Execucao) -> None:
        ibge = None
        if nome:
            row = conn.execute(
                "SELECT ibge, nome FROM municipio_ref WHERE uf = %s AND lower(nome) = lower(%s)", (uf, nome)
            ).fetchone()
            if not row:
                raise SystemExit(f"Carregue antes o município {nome}.")
            ibge = row[0]
        recompor = _com_tolerancia(execucao, lambda: fonte.codigos_recompor(uf, nome))
        sobreposicoes = _com_tolerancia(execucao, lambda: fonte.sobreposicoes(uf, nome))
        indice.gravar_indicadores(conn, uf, recompor, sobreposicoes, ibge)
        execucao.somar({"registros": len(recompor) + sum(map(len, sobreposicoes.values()))})
        if not nome:
            marcar_estado(conn, uf, indicadores_em=date.today())

    return executar(conn, fonte, "indicadores", uf, nome, tarefa)


def atualizar_retificacoes(conn: Conexao, fonte: FonteCar, uf: str, nome: str | None = None) -> dict[str, Any]:
    ciclo = f"retificacoes:{date.today():%Y-%m}"

    def tarefa(execucao: Execucao) -> None:
        municipios = _obter_municipios(conn, fonte, uf)
        if nome:
            municipios = [item for item in municipios if sicar.plain(item.nome) == sicar.plain(nome)]
        feitos = {
            row[0]
            for row in conn.execute(
                "SELECT chave FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
            ).fetchall()
        }
        for municipio in municipios:
            if str(municipio.ibge) in feitos:
                continue
            valores = _com_tolerancia(execucao, lambda: fonte.retificacoes(uf, municipio.nome))
            indice.gravar_retificacoes(conn, valores)
            execucao.somar({"registros": len(valores)})
            conn.execute(
                "INSERT INTO sync_checkpoint (uf, ciclo, chave) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (uf, ciclo, str(municipio.ibge)),
            )
            execucao.salvar()
            conn.commit()
        if not nome:
            marcar_estado(conn, uf, retificacoes_em=date.today())

    return executar(conn, fonte, "retificacoes", uf, nome, tarefa)


def sincronizar_diario(conn: Conexao, fonte: FonteCar, uf: str, hoje: date | None = None) -> dict[str, Any]:
    hoje = hoje or date.today()

    def tarefa(execucao: Execucao) -> None:
        row = conn.execute("SELECT marca FROM sync_estado WHERE uf = %s", (uf,)).fetchone()
        if not row or not row[0]:
            raise SystemExit("Faça a carga inicial antes da atualização diária.")
        desde = row[0] - timedelta(days=1)
        total = _com_tolerancia(execucao, lambda: fonte.total_alterados(uf, desde))
        if total > LIMITE_ALTERACOES:
            # Atualização em massa: a recarga mensal absorve aos poucos, por município.
            conn.execute(
                "UPDATE sync_execucao SET detalhe = %s WHERE id = %s",
                (f"{total} alterações; adiado para recarga gradual", execucao.id),
            )
            conn.execute(
                "DELETE FROM sync_checkpoint WHERE uf = %s AND ciclo = %s",
                (uf, f"recarga:{hoje:%Y-%m}"),
            )
            marcar_estado(conn, uf, ultimo_diario=hoje, marca=hoje)
            return
        apos: str | None = None
        while True:
            pagina = _com_tolerancia(execucao, lambda: fonte.alterados(uf, desde, apos))
            if pagina:
                execucao.somar(indice.gravar_cadastro(conn, pagina, historico=True, dia=hoje))
                execucao.salvar()
                conn.commit()
            if len(pagina) < CHANGE_PAGE_SIZE:
                break
            apos = pagina[-1]["cod_imovel"]
        marcar_estado(conn, uf, ultimo_diario=hoje, marca=hoje)

    return executar(conn, fonte, "diario", uf, None, tarefa)


def conferir_totais(conn: Conexao, fonte: FonteCar, uf: str) -> dict[str, Any]:
    ciclo = f"conferencia:{date.today():%G-W%V}"

    def tarefa(execucao: Execucao) -> None:
        locais = dict(
            conn.execute(
                "SELECT ibge, count(*) FROM indice_imovel WHERE uf = %s GROUP BY ibge", (uf,)
            ).fetchall()
        )
        feitos = {
            row[0]
            for row in conn.execute(
                "SELECT chave FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
            ).fetchall()
        }
        for municipio in _obter_municipios(conn, fonte, uf):
            if str(municipio.ibge) in feitos:
                continue
            total = _com_tolerancia(execucao, lambda: fonte.total_municipio(uf, municipio.ibge))
            if total != locais.get(municipio.ibge, 0):
                itens = _com_tolerancia(execucao, lambda: fonte.cadastro_municipio(uf, municipio.ibge))
                execucao.somar(indice.gravar_cadastro(conn, itens, (uf, municipio.ibge), historico=True))
            conn.execute(
                "INSERT INTO sync_checkpoint (uf, ciclo, chave) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (uf, ciclo, str(municipio.ibge)),
            )
            execucao.salvar()
            conn.commit()
        marcar_estado(conn, uf, ultima_conferencia=date.today())

    return executar(conn, fonte, "conferencia", uf, None, tarefa)


def atualizar_geometrias(conn: Conexao, fonte: FonteCar, uf: str, nome: str | None = None) -> dict[str, Any]:
    """Carrega limites por município e, depois, só os dos imóveis alterados."""
    ciclo = "geometrias:inicial"

    def tarefa(execucao: Execucao) -> None:
        municipios = _obter_municipios(conn, fonte, uf)
        if nome:
            municipios = [item for item in municipios if sicar.plain(item.nome) == sicar.plain(nome)]
        feitos = {
            row[0]
            for row in conn.execute(
                "SELECT chave FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
            ).fetchall()
        }
        pendentes = [item for item in municipios if str(item.ibge) not in feitos]
        for municipio in pendentes:
            itens = _com_tolerancia(execucao, lambda: fonte.geometrias_municipio(uf, municipio.ibge))
            execucao.somar({"registros": len(itens), "alterados": indice.gravar_geometrias(conn, itens)})
            conn.execute(
                "INSERT INTO sync_checkpoint (uf, ciclo, chave) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (uf, ciclo, str(municipio.ibge)),
            )
            execucao.salvar()
            conn.commit()
        if nome or pendentes:
            if not nome and _todos_concluidos(conn, uf, ciclo):
                marcar_estado(conn, uf, geometrias_em=datetime.now(timezone.utc))
            return
        inicio = datetime.now(timezone.utc)
        codigos = [row[0] for row in conn.execute(
            """SELECT i.cod_imovel FROM indice_imovel AS i
               LEFT JOIN geometria_imovel AS g USING (cod_imovel)
               WHERE i.uf = %s AND i.alterado_em > coalesce(g.atualizado_em,
                     (SELECT geometrias_em FROM sync_estado WHERE uf = %s))
               ORDER BY i.cod_imovel""",
            (uf, uf),
        ).fetchall()]
        for inicio_lote in range(0, len(codigos), LOTE_GEOMETRIAS):
            lote = codigos[inicio_lote:inicio_lote + LOTE_GEOMETRIAS]
            itens = _com_tolerancia(execucao, lambda: fonte.geometrias_codigos(uf, lote))
            execucao.somar({"registros": len(itens), "alterados": indice.gravar_geometrias(conn, itens)})
            execucao.salvar()
            conn.commit()
        marcar_estado(conn, uf, geometrias_em=inicio)

    return executar(conn, fonte, "geometrias", uf, nome, tarefa)


def _todos_concluidos(conn: Conexao, uf: str, ciclo: str) -> bool:
    return not _ciclo_pendente(conn, uf, ciclo)


def geometrias_pendentes(conn: Conexao, uf: str) -> bool:
    if _ciclo_pendente(conn, uf, "geometrias:inicial"):
        return True
    return bool(conn.execute(
        """SELECT EXISTS (SELECT 1 FROM indice_imovel AS i LEFT JOIN geometria_imovel AS g USING (cod_imovel)
           WHERE i.uf = %s AND i.alterado_em > coalesce(g.atualizado_em,
                 (SELECT geometrias_em FROM sync_estado WHERE uf = %s)))""",
        (uf, uf),
    ).fetchone()[0])


def finalizar(conn: Conexao, uf: str) -> dict[str, Any]:
    from . import agrupamento  # carregado só na rotina, pois o modelo é pesado

    resultado: dict[str, Any] = indice.recalcular_uf(conn, uf)
    conn.commit()
    resultado["agrupamento"] = agrupamento.agrupar(conn, uf)
    conn.commit()
    return resultado


def _ciclo_pendente(conn: Conexao, uf: str, ciclo: str) -> bool:
    total = conn.execute("SELECT count(*) FROM municipio_ref WHERE uf = %s", (uf,)).fetchone()[0]
    feitos = conn.execute(
        "SELECT count(*) FROM sync_checkpoint WHERE uf = %s AND ciclo = %s", (uf, ciclo)
    ).fetchone()[0]
    return total == 0 or feitos < total


def proxima_tarefa(conn: Conexao, fonte: FonteCar, uf: str) -> dict[str, Any] | None:
    """Escolhe uma tarefa por vez, sempre dentro do orçamento diário."""
    hoje = date.today()
    garantir_estado(conn, uf)
    conn.commit()
    estado = conn.execute(
        """SELECT carga_concluida_em, ultimo_diario, ultima_conferencia, indicadores_em, retificacoes_em
           FROM sync_estado WHERE uf = %s""",
        (uf,),
    ).fetchone()
    carga, diario, conferencia, indicadores, retificacoes = estado
    if not carga:
        return carregar_municipios(conn, fonte, uf, "carga")
    if not indicadores or (hoje - indicadores).days >= 7:
        return atualizar_indicadores(conn, fonte, uf)
    if diario != hoje:
        return sincronizar_diario(conn, fonte, uf, hoje)
    if not conferencia or (hoje - conferencia).days >= 7:
        return conferir_totais(conn, fonte, uf)
    if not retificacoes or (hoje - retificacoes).days >= 30:
        return atualizar_retificacoes(conn, fonte, uf)
    if geometrias_pendentes(conn, uf):
        return atualizar_geometrias(conn, fonte, uf)
    ciclo = f"recarga:{hoje:%Y-%m}"
    if _ciclo_pendente(conn, uf, ciclo):
        return carregar_municipios(conn, fonte, uf, ciclo)
    return None


def criar_fonte(conn: Conexao, intervalo: float, limite: int | None = None) -> ServicosPublicosCar:
    restante = max(0, ORCAMENTO_DIARIO - chamadas_de_hoje(conn))
    bytes_restantes = max(0, int(ORCAMENTO_MB_DIARIO * 1e6) - bytes_de_hoje(conn))
    return ServicosPublicosCar(
        intervalo, restante if limite is None else min(limite, restante), limite_bytes=bytes_restantes
    )


def loop(ufs: list[str], intervalo: float) -> None:
    while True:
        try:
            if dentro_da_janela():
                with psycopg.connect(sicar.DATABASE_URL) as conn:
                    indice.criar_esquema(conn)
                    conn.commit()
                    for uf in ufs:
                        with trava_uf(conn, uf) as livre:
                            if not livre:
                                continue
                            fonte = criar_fonte(conn, intervalo)
                            if fonte.limite_chamadas <= 0:
                                continue
                            try:
                                resultado = proxima_tarefa(conn, fonte, uf)
                            except RotinaPausada as exc:
                                print(exc, flush=True)
                                continue
                            if resultado:
                                print(json.dumps(resultado, ensure_ascii=False), flush=True)
                                print(json.dumps(finalizar(conn, uf), ensure_ascii=False), flush=True)
        except (psycopg.Error, OSError) as exc:
            print(f"Falha temporária: {exc}", flush=True)
        time.sleep(300)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uf", default=os.environ.get("SYNC_UFS", "MA"))
    parser.add_argument("--municipio")
    parser.add_argument("--carga", action="store_true")
    parser.add_argument("--indicadores", action="store_true")
    parser.add_argument("--retificacoes", action="store_true")
    parser.add_argument("--diario", action="store_true")
    parser.add_argument("--conferir", action="store_true")
    parser.add_argument("--geometrias", action="store_true")
    parser.add_argument("--recalcular", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--intervalo", type=float, default=INTERVALO)
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()
    ufs = [sicar.check_uf(item) for item in args.uf.split(",")]
    if args.loop:
        loop(ufs, args.intervalo)
        return
    uf = ufs[0]
    with psycopg.connect(sicar.DATABASE_URL) as conn:
        indice.criar_esquema(conn)
        conn.commit()
        with trava_uf(conn, uf) as livre:
            if not livre:
                raise SystemExit("Já existe uma sincronização em andamento para esta UF.")
            fonte = criar_fonte(conn, args.intervalo, args.limite)
            resultados = []
            try:
                if args.municipio:
                    resultados.append(carregar_municipios(conn, fonte, uf, "piloto", args.municipio))
                    conn.execute(
                        "DELETE FROM sync_checkpoint WHERE uf = %s AND ciclo = 'piloto'", (uf,)
                    )
                    conn.commit()
                    resultados.append(atualizar_indicadores(conn, fonte, uf, args.municipio))
                if args.carga:
                    resultados.append(carregar_municipios(conn, fonte, uf, "carga"))
                if args.indicadores and not args.municipio:
                    resultados.append(atualizar_indicadores(conn, fonte, uf))
                if args.retificacoes:
                    resultados.append(atualizar_retificacoes(conn, fonte, uf, args.municipio))
                if args.geometrias:
                    resultados.append(atualizar_geometrias(conn, fonte, uf, args.municipio))
                if args.diario:
                    resultados.append(sincronizar_diario(conn, fonte, uf))
                if args.conferir:
                    resultados.append(conferir_totais(conn, fonte, uf))
            except RotinaPausada as exc:
                raise SystemExit(str(exc)) from exc
            resultados.append({"recalculo": finalizar(conn, uf)})
            print(json.dumps(resultados, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
