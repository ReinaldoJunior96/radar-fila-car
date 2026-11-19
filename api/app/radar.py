"""Consultas do Radar. Tudo aqui lê o índice local e não chama o SICAR."""
from __future__ import annotations

import csv
import io
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


def status_sincronizacao() -> dict[str, Any]:
    with sicar.pool.connection() as conn:
        estados = conn.execute(
            """SELECT e.*, (SELECT count(*) FROM municipio_ref r WHERE r.uf = e.uf) AS municipios,
                      (SELECT count(DISTINCT ibge) FROM indice_imovel i WHERE i.uf = e.uf) AS municipios_indexados,
                      (SELECT count(*) FROM indice_imovel i WHERE i.uf = e.uf) AS imoveis,
                      (SELECT max(gerado_em) FROM resumo_municipio m WHERE m.uf = e.uf) AS resumo_em
               FROM sync_estado AS e ORDER BY e.uf"""
        ).fetchall()
        execucoes = conn.execute(
            """SELECT tipo, uf, detalhe, status, iniciado_em, terminado_em, chamadas, bytes,
                      registros, novos, alterados, removidos, erro
               FROM sync_execucao ORDER BY id DESC LIMIT 10"""
        ).fetchall()
        hoje = conn.execute(
            """SELECT coalesce(sum(chamadas), 0)::int AS c, coalesce(sum(bytes), 0)::bigint AS b
               FROM sync_execucao WHERE iniciado_em >= %s""",
            (sync_indice.agora_brasilia().replace(hour=0, minute=0, second=0, microsecond=0),),
        ).fetchone()
    return {
        "estados": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in linha.items()}
            for linha in estados
        ],
        "execucoes": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in linha.items()}
            for linha in execucoes
        ],
        "hoje": {"chamadas": hoje["c"], "bytes": hoje["b"], "orcamento": sync_indice.ORCAMENTO_DIARIO},
        "regras": {
            "intervalo_segundos": sync_indice.INTERVALO,
            "janela": f"{sync_indice.JANELA_INICIO:02d}:00 às 00:{sync_indice.JANELA_FIM_MINUTOS:02d}",
            "uma_chamada_por_vez": True,
        },
    }
