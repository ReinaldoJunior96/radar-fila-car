"""Consultas do Radar. Tudo aqui lê o índice local e não chama o SICAR."""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import classificacao, sicar, sync_indice
from .sicar import InvalidFilter

CONDICOES = {
    "aguardando_analise": "Aguardando análise",
    "em_analise": "Em análise",
    "analisado_notificacao": "Analisado, aguardando atendimento",
    "analisado_regularizacao": "Analisado, aguardando regularização",
    "analisado_conforme": "Analisado, em conformidade",
    "cancelado": "Cancelado",
    "outro": "Outra condição",
}
SITUACOES = {"AT": "Ativo", "PE": "Pendente", "SU": "Suspenso", "CA": "Cancelado"}
TIPOS = {"IRU": "Imóvel rural", "AST": "Assentamento", "PCT": "Povos e comunidades tradicionais"}
ORDENS = {
    "prioridade": "prioridade DESC, data_criacao ASC NULLS LAST, cod_imovel",
    "antiguidade": "data_criacao ASC NULLS LAST, cod_imovel",
    "area": "area_ha DESC NULLS LAST, cod_imovel",
}
ESTADOS = [
    {"uf": "AC", "nome": "Acre"},
    {"uf": "AL", "nome": "Alagoas"},
    {"uf": "AM", "nome": "Amazonas"},
    {"uf": "AP", "nome": "Amapá"},
    {"uf": "BA", "nome": "Bahia"},
    {"uf": "CE", "nome": "Ceará"},
    {"uf": "DF", "nome": "Distrito Federal"},
    {"uf": "ES", "nome": "Espírito Santo"},
    {"uf": "GO", "nome": "Goiás"},
    {"uf": "MA", "nome": "Maranhão"},
    {"uf": "MG", "nome": "Minas Gerais"},
    {"uf": "MS", "nome": "Mato Grosso do Sul"},
    {"uf": "MT", "nome": "Mato Grosso"},
    {"uf": "PA", "nome": "Pará"},
    {"uf": "PB", "nome": "Paraíba"},
    {"uf": "PE", "nome": "Pernambuco"},
    {"uf": "PI", "nome": "Piauí"},
    {"uf": "PR", "nome": "Paraná"},
    {"uf": "RJ", "nome": "Rio de Janeiro"},
    {"uf": "RN", "nome": "Rio Grande do Norte"},
    {"uf": "RO", "nome": "Rondônia"},
    {"uf": "RR", "nome": "Roraima"},
    {"uf": "RS", "nome": "Rio Grande do Sul"},
    {"uf": "SC", "nome": "Santa Catarina"},
    {"uf": "SE", "nome": "Sergipe"},
    {"uf": "SP", "nome": "São Paulo"},
    {"uf": "TO", "nome": "Tocantins"},
]
LIMITE_EXPORTACAO = 50000
AVISO = (
    "Perfis e prioridade organizam dados públicos declaratórios para triagem. "
    "Não indicam regularidade ou irregularidade ambiental."
)


@dataclass
class FiltroFila:
    uf: str
    ibge: int | None = None
    perfis: list[str] = field(default_factory=list)
    condicao: str | None = None
    status: str | None = None
    tipo: str | None = None
    prioridade_min: int | None = None
    anos_min: float | None = None
    area_min: float | None = None
    area_max: float | None = None
    grupo: int | None = None
    com_sobreposicao: bool = False
    analisado_desde: date | None = None
    alterado_desde: date | None = None
    atualizado_desde: date | None = None
    bbox: tuple[float, float, float, float] | None = None
    ordem: str = "prioridade"

    def validar(self) -> "FiltroFila":
        self.uf = sicar.check_uf(self.uf)
        desconhecidos = [item for item in self.perfis if item not in classificacao.POR_CODIGO]
        if desconhecidos:
            raise InvalidFilter(f"Perfil desconhecido: {desconhecidos[0]}.")
        if self.condicao and self.condicao not in CONDICOES:
            raise InvalidFilter("Condição desconhecida.")
        if self.status and self.status not in SITUACOES:
            raise InvalidFilter("Situação desconhecida.")
        if self.tipo and self.tipo not in TIPOS:
            raise InvalidFilter("Tipo de imóvel desconhecido.")
        if self.ordem not in ORDENS:
            raise InvalidFilter("Ordenação desconhecida.")
        if self.area_min is not None and self.area_max is not None and self.area_min > self.area_max:
            raise InvalidFilter("A área mínima não pode superar a máxima.")
        if self.bbox:
            oeste, sul, leste, norte = self.bbox
            if not (-180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90):
                raise InvalidFilter("Retângulo inválido: use oeste, sul, leste e norte em graus.")
        return self

    def where(self, hoje: date | None = None) -> tuple[str, list[Any]]:
        hoje = hoje or date.today()
        partes, valores = ["uf = %s"], [self.uf]
        simples = [
            ("ibge = %s", self.ibge), ("condicao_grupo = %s", self.condicao),
            ("status = %s", self.status), ("tipo = %s", self.tipo),
            ("prioridade >= %s", self.prioridade_min), ("area_ha >= %s", self.area_min),
            ("area_ha <= %s", self.area_max), ("grupo = %s", self.grupo),
        ]
        for clausula, valor in simples:
            if valor is not None:
                partes.append(clausula)
                valores.append(valor)
        if self.perfis:
            partes.append("perfis @> %s")
            valores.append(self.perfis)
        if self.anos_min is not None:
            partes.append("data_criacao <= %s")
            valores.append(hoje - timedelta(days=round(self.anos_min * 365.25)))
        if self.com_sobreposicao:
            partes.append("sobreposicoes <> '{}'")
        if self.analisado_desde:
            partes.append(
                """EXISTS (SELECT 1 FROM historico_imovel AS h WHERE h.cod_imovel = indice_imovel.cod_imovel
                   AND h.evento = 'condicao' AND h.condicao_nova LIKE 'analisado%%' AND h.dia >= %s)"""
            )
            valores.append(self.analisado_desde)
        if self.alterado_desde:
            partes.append(
                """EXISTS (SELECT 1 FROM historico_imovel AS h WHERE h.cod_imovel = indice_imovel.cod_imovel
                   AND h.evento IN ('condicao', 'situacao') AND h.dia >= %s)"""
            )
            valores.append(self.alterado_desde)
        if self.atualizado_desde:
            partes.append("data_atualizacao >= %s")
            valores.append(self.atualizado_desde)
        if self.bbox:
            partes.append(
                """EXISTS (SELECT 1 FROM geometria_imovel AS g WHERE g.cod_imovel = indice_imovel.cod_imovel
                   AND ST_Intersects(g.geom, ST_MakeEnvelope(%s, %s, %s, %s, 4674)))"""
            )
            valores.extend(self.bbox)
        return " AND ".join(partes), valores


def _item(linha: dict[str, Any], hoje: date) -> dict[str, Any]:
    idade = classificacao.idade_anos(linha, hoje)
    return {
        "codigo_car": linha["cod_imovel"],
        "municipio": linha["municipio"],
        "ibge": linha["ibge"],
        "uf": linha["uf"],
        "situacao": linha["status"],
        "situacao_rotulo": SITUACOES.get(linha["status"], linha["status"]),
        "tipo": linha["tipo"],
        "condicao": linha["condicao"],
        "condicao_grupo": linha["condicao_grupo"],
        "area_ha": linha["area_ha"],
        "modulos_fiscais": linha["modulos"],
        "data_criacao": linha["data_criacao"].isoformat() if linha["data_criacao"] else None,
        "data_atualizacao": linha["data_atualizacao"].isoformat() if linha["data_atualizacao"] else None,
        "anos_desde_criacao": round(idade, 1) if idade is not None else None,
        "retificacoes": linha["retificacoes"],
        "prioridade_sugerida": linha["prioridade"],
        "grupo": linha["grupo"],
        "perfis": classificacao.motivos(linha["perfis"]),
    }


def fila(filtro: FiltroFila, pagina: int = 1, por_pagina: int = 25) -> dict[str, Any]:
    filtro.validar()
    where, valores = filtro.where()
    hoje = date.today()
    with sicar.pool.connection() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM indice_imovel WHERE {where}", valores).fetchone()["n"]
        linhas = conn.execute(
            f"""SELECT * FROM indice_imovel WHERE {where}
                ORDER BY {ORDENS[filtro.ordem]} LIMIT %s OFFSET %s""",
            [*valores, por_pagina, (pagina - 1) * por_pagina],
        ).fetchall()
    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": (total + por_pagina - 1) // por_pagina,
        "itens": [_item(linha, hoje) for linha in linhas],
        "chamadas_sicar": 0,
        "aviso": AVISO,
    }


def ranking(filtro: FiltroFila, limite: int = 10) -> list[dict[str, Any]]:
    filtro.validar()
    where, valores = filtro.where()
    with sicar.pool.connection() as conn:
        return conn.execute(
            f"""SELECT municipio, ibge, count(*) AS total FROM indice_imovel WHERE {where}
                GROUP BY municipio, ibge ORDER BY total DESC, municipio LIMIT %s""",
            [*valores, limite],
        ).fetchall()


def exportar(filtro: FiltroFila) -> tuple[str, int]:
    filtro.validar()
    where, valores = filtro.where()
    hoje = date.today()
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow([
        "codigo_car", "municipio", "uf", "situacao", "tipo", "condicao", "area_ha", "modulos_fiscais",
        "data_criacao", "data_atualizacao", "anos_desde_criacao", "retificacoes",
        "prioridade_sugerida", "perfis",
    ])
    with sicar.pool.connection() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM indice_imovel WHERE {where}", valores).fetchone()["n"]
        if total > LIMITE_EXPORTACAO:
            raise InvalidFilter(
                f"A exportação aceita até {LIMITE_EXPORTACAO:,} imóveis; este filtro tem {total:,}.".replace(",", ".")
            )
        for linha in conn.execute(
            f"SELECT * FROM indice_imovel WHERE {where} ORDER BY {ORDENS[filtro.ordem]}", valores
        ):
            item = _item(linha, hoje)
            escritor.writerow([
                item["codigo_car"], item["municipio"], item["uf"], item["situacao"], item["tipo"],
                item["condicao"], item["area_ha"], item["modulos_fiscais"], item["data_criacao"],
                item["data_atualizacao"], item["anos_desde_criacao"], item["retificacoes"],
                item["prioridade_sugerida"], "; ".join(perfil["rotulo"] for perfil in item["perfis"]),
            ])
    return saida.getvalue(), total


def resumo(uf: str, ibge: int | None = None) -> dict[str, Any]:
    uf = sicar.check_uf(uf)
    with sicar.pool.connection() as conn:
        linha = conn.execute(
            "SELECT municipio, dados, gerado_em FROM resumo_municipio WHERE uf = %s AND ibge = %s",
            (uf, ibge or 0),
        ).fetchone()
    if not linha:
        return {"disponivel": False, "uf": uf, "ibge": ibge}
    return {
        "disponivel": True,
        "uf": uf,
        "ibge": ibge,
        "nome": linha["municipio"],
        "gerado_em": linha["gerado_em"].isoformat(),
        **linha["dados"],
        "condicoes_rotulos": CONDICOES,
        "chamadas_sicar": 0,
        "aviso": AVISO,
    }


def recorte(filtro: FiltroFila, limite_municipios: int = 10) -> dict[str, Any]:
    """Indicadores do recorte filtrado, no mesmo formato do resumo, calculados numa única consulta."""
    filtro.validar()
    inicio = time.perf_counter()
    if filtro.where()[0] == FiltroFila(uf=filtro.uf, ibge=filtro.ibge).where()[0]:
        pronto = _recorte_pre_calculado(filtro, limite_municipios)
        if pronto:
            pronto["tempo_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
            return pronto
    where, valores = filtro.where()
    hoje = date.today()
    sql = f"""
        WITH r AS MATERIALIZED (
            SELECT ibge, municipio, status, condicao_grupo, area_ha, prioridade, perfis, data_criacao,
                   CASE WHEN condicao_grupo = 'aguardando_analise' AND data_criacao IS NOT NULL
                        THEN greatest((%s::date - data_criacao) / 365.25, 0) END AS idade
            FROM indice_imovel WHERE {where}
        )
        SELECT
            (SELECT count(*) FROM r) AS total,
            (SELECT coalesce(sum(area_ha), 0) FROM r) AS area_ha,
            (SELECT coalesce(avg(prioridade), 0) FROM r) AS prioridade_media,
            (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY idade) FROM r WHERE idade IS NOT NULL) AS idade_mediana,
            (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY idade) FROM r WHERE idade IS NOT NULL) AS idade_p90,
            (SELECT coalesce(jsonb_object_agg(k, n), '{{}}') FROM (SELECT coalesce(condicao_grupo, 'outro') AS k, count(*) AS n FROM r GROUP BY 1) x) AS condicoes,
            (SELECT coalesce(jsonb_object_agg(k, n), '{{}}') FROM (SELECT coalesce(status, 'NI') AS k, count(*) AS n FROM r GROUP BY 1) x) AS status,
            (SELECT coalesce(jsonb_object_agg(k, n), '{{}}') FROM (SELECT p AS k, count(*) AS n FROM r, unnest(perfis) AS p GROUP BY 1) x) AS perfis,
            (SELECT coalesce(jsonb_object_agg(k, n), '{{}}') FROM (
                SELECT CASE WHEN idade < 1 THEN 'ate_1' WHEN idade < 3 THEN '1_3' WHEN idade < 5 THEN '3_5'
                            WHEN idade < 10 THEN '5_10' ELSE '10_mais' END AS k, count(*) AS n
                FROM r WHERE idade IS NOT NULL GROUP BY 1) x) AS faixas_fila,
            (SELECT coalesce(jsonb_object_agg(k, n), '{{}}') FROM (
                SELECT CASE WHEN prioridade < 25 THEN '0_24' WHEN prioridade < 50 THEN '25_49'
                            WHEN prioridade < 75 THEN '50_74' ELSE '75_100' END AS k, count(*) AS n
                FROM r GROUP BY 1) x) AS faixas_prioridade,
            (SELECT coalesce(jsonb_agg(c ORDER BY c->>'ano'), '[]') FROM (
                SELECT jsonb_build_object('ano', extract(year FROM data_criacao)::int, 'total', count(*),
                       'sem_analise', count(*) FILTER (WHERE condicao_grupo = 'aguardando_analise')) AS c
                FROM r WHERE data_criacao IS NOT NULL GROUP BY extract(year FROM data_criacao)) x) AS coortes,
            (SELECT count(DISTINCT ibge) FROM r) AS municipios_no_recorte,
            (SELECT coalesce(jsonb_agg(m), '[]') FROM (
                SELECT jsonb_build_object('ibge', ibge, 'municipio', municipio, 'total', count(*),
                       'sem_analise', count(*) FILTER (WHERE condicao_grupo = 'aguardando_analise')) AS m
                FROM r GROUP BY ibge, municipio ORDER BY count(*) DESC, municipio LIMIT %s) x) AS municipios
    """
    with sicar.pool.connection() as conn:
        linha = conn.execute(sql, [hoje, *valores, limite_municipios]).fetchone()
    total = linha["total"]
    sem = linha["condicoes"].get("aguardando_analise", 0)
    arredonda = lambda v: round(float(v), 1) if v is not None else None
    return {
        "uf": filtro.uf,
        "ibge": filtro.ibge,
        "total": total,
        "area_ha": round(float(linha["area_ha"]), 2),
        "sem_analise": sem,
        "sem_analise_pct": round(100 * sem / total, 1) if total else 0,
        "idade_mediana_anos": arredonda(linha["idade_mediana"]),
        "idade_p90_anos": arredonda(linha["idade_p90"]),
        "prioridade_media": arredonda(linha["prioridade_media"]),
        "condicoes": linha["condicoes"],
        "status": linha["status"],
        "perfis": linha["perfis"],
        "faixas_fila": {nome: linha["faixas_fila"].get(nome, 0) for nome in ("ate_1", "1_3", "3_5", "5_10", "10_mais")},
        "faixas_prioridade": {nome: linha["faixas_prioridade"].get(nome, 0) for nome in ("0_24", "25_49", "50_74", "75_100")},
        "coortes": linha["coortes"],
        "municipios_no_recorte": linha["municipios_no_recorte"],
        "municipios": linha["municipios"],
        "condicoes_rotulos": CONDICOES,
        "tempo_ms": round((time.perf_counter() - inicio) * 1000, 1),
        "chamadas_sicar": 0,
        "aviso": AVISO,
    }


def _recorte_pre_calculado(filtro: FiltroFila, limite: int) -> dict[str, Any] | None:
    """Sem filtros além do território, usa o resumo gravado pela sincronização."""
    base = resumo(filtro.uf, filtro.ibge)
    if not base.get("disponivel"):
        return None
    with sicar.pool.connection() as conn:
        faixas = conn.execute(
            f"""SELECT CASE WHEN prioridade < 25 THEN '0_24' WHEN prioridade < 50 THEN '25_49'
                            WHEN prioridade < 75 THEN '50_74' ELSE '75_100' END AS k, count(*) AS n
                FROM indice_imovel WHERE uf = %s {"AND ibge = %s" if filtro.ibge else ""} GROUP BY 1""",
            [filtro.uf, filtro.ibge] if filtro.ibge else [filtro.uf],
        ).fetchall()
        if filtro.ibge:
            cidades = [{"ibge": filtro.ibge, "municipio": base["nome"], "total": base["total"], "sem_analise": base["sem_analise"]}]
            quantidade = 1
        else:
            linhas = conn.execute(
                """SELECT ibge, municipio, (dados->>'total')::int AS total, (dados->>'sem_analise')::int AS sem_analise
                   FROM resumo_municipio WHERE uf = %s AND ibge <> 0 ORDER BY (dados->>'total')::int DESC, municipio""",
                (filtro.uf,),
            ).fetchall()
            cidades, quantidade = [dict(l) for l in linhas[:limite]], len(linhas)
    mapa_faixas = {l["k"]: l["n"] for l in faixas}
    return {
        "uf": filtro.uf, "ibge": filtro.ibge,
        **{k: base[k] for k in ("total", "area_ha", "sem_analise", "sem_analise_pct", "idade_mediana_anos",
                                "idade_p90_anos", "prioridade_media", "condicoes", "status", "perfis",
                                "faixas_fila", "coortes", "condicoes_rotulos")},
        "faixas_prioridade": {nome: mapa_faixas.get(nome, 0) for nome in ("0_24", "25_49", "50_74", "75_100")},
        "municipios_no_recorte": quantidade, "municipios": cidades,
        "pre_calculado": True, "gerado_em": base["gerado_em"], "chamadas_sicar": 0, "aviso": AVISO,
    }


def municipios(uf: str) -> list[dict[str, Any]]:
    uf = sicar.check_uf(uf)
    with sicar.pool.connection() as conn:
        linhas = conn.execute(
            """SELECT ibge, municipio, lon, lat, dados FROM resumo_municipio
               WHERE uf = %s AND ibge <> 0 ORDER BY municipio""",
            (uf,),
        ).fetchall()
    return [
        {
            "ibge": linha["ibge"],
            "municipio": linha["municipio"],
            "lon": linha["lon"],
            "lat": linha["lat"],
            "total": linha["dados"]["total"],
            "sem_analise": linha["dados"]["sem_analise"],
            "sem_analise_pct": linha["dados"]["sem_analise_pct"],
            "idade_mediana_anos": linha["dados"]["idade_mediana_anos"],
            "prioridade_media": linha["dados"]["prioridade_media"],
            "fila_5_anos": linha["dados"]["perfis"].get("fila_5_anos", 0),
            "app_recompor": linha["dados"]["perfis"].get("app_recompor", 0),
        }
        for linha in linhas
    ]


def evolucao(uf: str, ibge: int | None = None) -> dict[str, Any]:
    uf = sicar.check_uf(uf)
    filtro = "AND ibge = %s" if ibge else ""
    valores: list[Any] = [uf, ibge] if ibge else [uf]
    with sicar.pool.connection() as conn:
        linhas = conn.execute(
            f"""SELECT dia, condicao_grupo, sum(total)::int AS total FROM snapshot_municipio
                WHERE uf = %s {filtro} GROUP BY dia, condicao_grupo ORDER BY dia""",
            valores,
        ).fetchall()
    dias: dict[str, dict[str, int]] = {}
    for linha in linhas:
        dias.setdefault(linha["dia"].isoformat(), {})[linha["condicao_grupo"]] = linha["total"]
    return {
        "serie": [{"dia": dia, "condicoes": valores_dia} for dia, valores_dia in dias.items()],
        "aviso": "A série começa na primeira sincronização; o SICAR público não oferece histórico de condição.",
    }


def grupos(uf: str) -> dict[str, Any]:
    uf = sicar.check_uf(uf)
    with sicar.pool.connection() as conn:
        linhas = conn.execute(
            "SELECT grupo, rotulo, total, caracteristicas, qualidade, gerado_em FROM indice_grupo WHERE uf = %s ORDER BY grupo",
            (uf,),
        ).fetchall()
    return {
        "grupos": [
            {"grupo": l["grupo"], "rotulo": l["rotulo"], "total": l["total"], **l["caracteristicas"]}
            for l in linhas
        ],
        "qualidade": linhas[0]["qualidade"] if linhas else None,
        "aviso": "Padrões exploratórios, úteis para investigar a base. Não são categorias oficiais.",
    }


def perfis(uf: str | None = None, ibge: int | None = None) -> dict[str, Any]:
    totais = resumo(uf, ibge).get("perfis", {}) if uf else {}
    return {
        "versao": classificacao.VERSAO,
        "perfis": [{**item, "total": totais.get(item["codigo"])} for item in classificacao.catalogo()],
        "aviso": AVISO,
    }


TAREFAS = [
    ("carga", "Carga inicial", None, "carga_concluida_em"),
    ("indicadores", "Indicadores ambientais", 7, "indicadores_em"),
    ("diario", "Atualização diária", 1, "ultimo_diario"),
    ("conferencia", "Conferência de totais", 7, "ultima_conferencia"),
    ("retificacoes", "Retificações", 30, "retificacoes_em"),
    ("geometrias", "Limites dos imóveis", None, "geometrias_em"),
]


def _texto(valor: Any) -> Any:
    return valor.isoformat() if hasattr(valor, "isoformat") else valor


def _tarefas(estado: dict[str, Any], hoje: date, ativa: str | None) -> list[dict[str, Any]]:
    itens = []
    for codigo, rotulo, dias, campo in TAREFAS:
        ultima = estado.get(campo)
        if hasattr(ultima, "date"):
            ultima = ultima.astimezone(sicar.BRASILIA).date()
        proxima = ultima + timedelta(days=dias) if ultima and dias else None
        if codigo == "geometrias" and estado.get("municipios") and estado.get("municipios_geometria", 0) < estado["municipios"]:
            situacao = "em_andamento" if ativa == codigo else "pendente"
        elif ativa == codigo:
            situacao = "em_andamento"
        elif ultima and (proxima is None or proxima > hoje):
            situacao = "em_dia"
        else:
            situacao = "pendente"
        itens.append({
            "codigo": codigo, "rotulo": rotulo, "frequencia_dias": dias,
            "ultima": _texto(ultima), "proxima": _texto(proxima), "situacao": situacao,
        })
    return itens


def status_sincronizacao() -> dict[str, Any]:
    agora = sync_indice.agora_brasilia()
    hoje = agora.date()
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    with sicar.pool.connection() as conn:
        estados = conn.execute(
            """SELECT e.*, (SELECT count(*) FROM municipio_ref r WHERE r.uf = e.uf) AS municipios,
                      (SELECT count(DISTINCT ibge) FROM indice_imovel i WHERE i.uf = e.uf) AS municipios_indexados,
                      (SELECT count(*) FROM indice_imovel i WHERE i.uf = e.uf) AS imoveis,
                      (SELECT max(gerado_em) FROM resumo_municipio m WHERE m.uf = e.uf) AS resumo_em,
                      (SELECT count(*) FROM sync_checkpoint c WHERE c.uf = e.uf AND c.ciclo = %s) AS recarga_feitos,
                      (SELECT count(*) FROM sync_checkpoint c WHERE c.uf = e.uf AND c.ciclo = 'geometrias:inicial') AS municipios_geometria,
                      (SELECT count(*) FROM geometria_imovel g WHERE g.uf = e.uf) AS geometrias,
                      (SELECT min(dia) FROM historico_imovel h WHERE h.uf = e.uf) AS historico_desde
               FROM sync_estado AS e ORDER BY e.uf""",
            (f"recarga:{hoje:%Y-%m}",),
        ).fetchall()
        execucoes = conn.execute(
            """SELECT id, tipo, uf, detalhe, status, iniciado_em, terminado_em, chamadas, bytes,
                      registros, novos, alterados, removidos, erro,
                      (status = 'em_andamento' AND iniciado_em > now() - interval '3 hours') AS ativa
               FROM sync_execucao ORDER BY id DESC LIMIT 12"""
        ).fetchall()
        hoje_uso = conn.execute(
            """SELECT coalesce(sum(chamadas), 0)::int AS c, coalesce(sum(bytes), 0)::bigint AS b
               FROM sync_execucao WHERE iniciado_em >= %s""",
            (inicio_dia,),
        ).fetchone()
        totais = conn.execute(
            """SELECT coalesce(sum(chamadas), 0)::int AS chamadas, coalesce(sum(bytes), 0)::bigint AS bytes,
                      count(*)::int AS execucoes, min(iniciado_em) AS desde
               FROM sync_execucao"""
        ).fetchone()
        por_dia = conn.execute(
            """SELECT (iniciado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
                      sum(chamadas)::int AS chamadas, sum(bytes)::bigint AS bytes
               FROM sync_execucao WHERE iniciado_em >= %s
               GROUP BY 1 ORDER BY 1""",
            (inicio_dia - timedelta(days=13),),
        ).fetchall()
    ativas = {(linha["uf"], linha["tipo"]) for linha in execucoes if linha["ativa"]}
    saida_estados = []
    for linha in estados:
        ativa = next((tipo for uf, tipo in ativas if uf == linha["uf"]), None)
        saida_estados.append({
            **{k: _texto(v) for k, v in linha.items()},
            "tarefas": _tarefas(linha, hoje, ativa),
        })
    return {
        "estados": saida_estados,
        "execucoes": [{k: _texto(v) for k, v in linha.items()} for linha in execucoes],
        "hoje": {"chamadas": hoje_uso["c"], "bytes": hoje_uso["b"], "orcamento": sync_indice.ORCAMENTO_DIARIO},
        "totais": {k: _texto(v) for k, v in totais.items()},
        "por_dia": [{k: _texto(v) for k, v in linha.items()} for linha in por_dia],
        "regras": {
            "intervalo_segundos": sync_indice.INTERVALO,
            "janela": f"{sync_indice.JANELA_INICIO:02d}:00 às 00:{sync_indice.JANELA_FIM_MINUTOS:02d}",
            "orcamento_diario": sync_indice.ORCAMENTO_DIARIO,
            "orcamento_mb_diario": sync_indice.ORCAMENTO_MB_DIARIO,
            "uma_chamada_por_vez": True,
        },
    }


ROTULOS_MOVIMENTO = {
    "novo": "Novos cadastros", "removido": "Removidos", "em_analise": "Entraram em análise",
    "analisado": "Concluíram análise", "cancelado": "Cancelados", "aguardando_analise": "Voltaram para análise",
    "outro": "Outras mudanças",
}


def _tipo_movimento(evento: str, nova: str | None) -> str:
    if evento in {"novo", "removido"}:
        return evento
    if evento != "condicao" or not nova:
        return "outro"
    if nova.startswith("analisado"):
        return "analisado"
    return nova if nova in {"em_analise", "cancelado", "aguardando_analise"} else "outro"


def movimentos(uf: str, ibge: int | None = None, dias: int = 90) -> dict[str, Any]:
    """Linha do tempo: etapas por dia e mudanças detectadas pela sincronização."""
    uf = sicar.check_uf(uf)
    filtro = "AND ibge = %s" if ibge else ""
    inicio = date.today() - timedelta(days=dias)
    valores: list[Any] = [uf, inicio, *([ibge] if ibge else [])]
    with sicar.pool.connection() as conn:
        eventos = conn.execute(
            f"""SELECT dia, evento, condicao_nova, count(*)::int AS total FROM historico_imovel
                WHERE uf = %s AND dia >= %s {filtro} AND evento <> 'cadastro'
                GROUP BY dia, evento, condicao_nova ORDER BY dia""",
            valores,
        ).fetchall()
        desde = conn.execute(
            f"SELECT min(dia) AS d FROM historico_imovel WHERE uf = %s {filtro}", [uf, *([ibge] if ibge else [])]
        ).fetchone()["d"]
    por_dia: dict[str, dict[str, int]] = {}
    for linha in eventos:
        tipo = _tipo_movimento(linha["evento"], linha["condicao_nova"])
        dia = por_dia.setdefault(linha["dia"].isoformat(), {})
        dia[tipo] = dia.get(tipo, 0) + linha["total"]
    return {
        "etapas": evolucao(uf, ibge)["serie"],
        "movimentos": [{"dia": dia, **valores_dia} for dia, valores_dia in por_dia.items()],
        "rotulos": ROTULOS_MOVIMENTO,
        "historico_desde": desde.isoformat() if desde else None,
        "aviso": "Mudanças registradas a cada sincronização. O SICAR público não informa a data das análises anteriores.",
    }


def imovel(codigo: str) -> dict[str, Any] | None:
    with sicar.pool.connection() as conn:
        linha = conn.execute("SELECT * FROM indice_imovel WHERE cod_imovel = %s", (codigo,)).fetchone()
        if not linha:
            return None
        historico = conn.execute(
            """SELECT dia, evento, condicao_anterior, condicao_nova, status_anterior, status_novo
               FROM historico_imovel WHERE cod_imovel = %s ORDER BY dia, id""",
            (codigo,),
        ).fetchall()
        geometria = conn.execute(
            "SELECT round((ST_Area(geom::geography) / 10000)::numeric, 2) AS area FROM geometria_imovel WHERE cod_imovel = %s",
            (codigo,),
        ).fetchone()
        estado = conn.execute("SELECT carga_concluida_em FROM sync_estado WHERE uf = %s", (linha["uf"],)).fetchone()
    return {
        **_item(linha, date.today()),
        "no_indice_desde": estado["carga_concluida_em"].date().isoformat() if estado and estado["carga_concluida_em"] else None,
        "historico": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in h.items()} for h in historico
        ],
        "area_limite_ha": float(geometria["area"]) if geometria else None,
        "condicoes_rotulos": CONDICOES,
        "chamadas_sicar": 0,
    }


LIMITE_MAPA = 8000


def mapa(filtro: FiltroFila) -> dict[str, Any]:
    """Limites simplificados do recorte, lidos do índice espacial local."""
    filtro.validar()
    if not filtro.ibge and not filtro.bbox:
        raise InvalidFilter("Escolha um município ou uma área para ver os limites.")
    where, valores = filtro.where()
    with sicar.pool.connection() as conn:
        linhas = conn.execute(
            f"""SELECT i.cod_imovel, i.prioridade, i.condicao_grupo, ST_AsGeoJSON(g.geom, 5)::json AS geometria
                FROM (SELECT cod_imovel, prioridade, condicao_grupo FROM indice_imovel WHERE {where}) AS i
                JOIN geometria_imovel AS g USING (cod_imovel)
                ORDER BY i.prioridade DESC, i.cod_imovel LIMIT %s""",
            [*valores, LIMITE_MAPA + 1],
        ).fetchall()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": linha["geometria"],
                "properties": {"codigo": linha["cod_imovel"], "prioridade": linha["prioridade"], "condicao": linha["condicao_grupo"]},
            }
            for linha in linhas[:LIMITE_MAPA]
        ],
        "truncado": len(linhas) > LIMITE_MAPA,
        "limite": LIMITE_MAPA,
        "chamadas_sicar": 0,
    }
