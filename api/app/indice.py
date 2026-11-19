"""Índice leve do CAR: atributos por imóvel e resumos, sem geometrias."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import classificacao
from .fonte import Municipio

COLUNAS = [
    "cod_imovel", "uf", "municipio", "ibge", "status", "tipo", "condicao", "condicao_grupo",
    "area_ha", "modulos", "data_criacao", "data_atualizacao", "hash",
]
FAIXAS = [("ate_1", 0, 1), ("1_3", 1, 3), ("3_5", 3, 5), ("5_10", 5, 10), ("10_mais", 10, 1000)]


def criar_esquema(conn: psycopg.Connection[Any]) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS indice_imovel (
            cod_imovel text PRIMARY KEY,
            uf text NOT NULL,
            municipio text NOT NULL,
            ibge integer NOT NULL,
            status text,
            tipo text,
            condicao text,
            condicao_grupo text,
            area_ha double precision,
            modulos double precision,
            data_criacao date,
            data_atualizacao date,
            hash text NOT NULL,
            tem_app_recompor boolean NOT NULL DEFAULT false,
            sobreposicoes text[] NOT NULL DEFAULT '{}',
            retificacoes integer,
            perfis text[] NOT NULL DEFAULT '{}',
            prioridade integer NOT NULL DEFAULT 0,
            grupo integer,
            visto_em timestamptz NOT NULL DEFAULT now(),
            alterado_em timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS indice_imovel_mun_idx ON indice_imovel (uf, ibge)",
        "CREATE INDEX IF NOT EXISTS indice_imovel_prio_idx ON indice_imovel (uf, prioridade DESC, cod_imovel)",
        "CREATE INDEX IF NOT EXISTS indice_imovel_perfis_idx ON indice_imovel USING gin (perfis)",
        "CREATE INDEX IF NOT EXISTS indice_imovel_condicao_idx ON indice_imovel (uf, condicao_grupo)",
        """CREATE TABLE IF NOT EXISTS municipio_ref (
            uf text NOT NULL, ibge integer NOT NULL, nome text NOT NULL,
            lon double precision, lat double precision, PRIMARY KEY (uf, ibge))""",
        """CREATE TABLE IF NOT EXISTS indice_perfil (
            codigo text PRIMARY KEY, rotulo text NOT NULL, descricao text NOT NULL,
            fonte text NOT NULL, peso integer NOT NULL, grupo text NOT NULL, versao text NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS indice_grupo (
            uf text NOT NULL, grupo integer NOT NULL, rotulo text NOT NULL, total integer NOT NULL,
            caracteristicas jsonb NOT NULL, qualidade jsonb NOT NULL, gerado_em timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (uf, grupo))""",
        """CREATE TABLE IF NOT EXISTS sync_estado (
            uf text PRIMARY KEY, carga_concluida_em timestamptz, marca date, ultimo_diario date,
            ultima_conferencia date, indicadores_em date, retificacoes_em date,
            pausado_ate timestamptz, motivo_pausa text)""",
        """CREATE TABLE IF NOT EXISTS sync_execucao (
            id bigserial PRIMARY KEY, tipo text NOT NULL, uf text NOT NULL, detalhe text,
            iniciado_em timestamptz NOT NULL DEFAULT now(), terminado_em timestamptz,
            status text NOT NULL DEFAULT 'em_andamento', chamadas integer NOT NULL DEFAULT 0,
            bytes bigint NOT NULL DEFAULT 0, registros integer NOT NULL DEFAULT 0,
            novos integer NOT NULL DEFAULT 0, alterados integer NOT NULL DEFAULT 0,
            removidos integer NOT NULL DEFAULT 0, erro text)""",
        """CREATE TABLE IF NOT EXISTS sync_checkpoint (
            uf text NOT NULL, ciclo text NOT NULL, chave text NOT NULL,
            concluido_em timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (uf, ciclo, chave))""",
        """CREATE TABLE IF NOT EXISTS resumo_municipio (
            uf text NOT NULL, ibge integer NOT NULL, municipio text NOT NULL,
            lon double precision, lat double precision, dados jsonb NOT NULL,
            gerado_em timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (uf, ibge))""",
        """CREATE TABLE IF NOT EXISTS historico_imovel (
            id bigserial PRIMARY KEY, cod_imovel text NOT NULL, uf text NOT NULL, ibge integer NOT NULL,
            dia date NOT NULL, evento text NOT NULL, condicao_anterior text, condicao_nova text,
            status_anterior text, status_novo text, registrado_em timestamptz NOT NULL DEFAULT now())""",
        "CREATE INDEX IF NOT EXISTS historico_imovel_codigo_idx ON historico_imovel (cod_imovel, dia)",
        "CREATE INDEX IF NOT EXISTS historico_imovel_dia_idx ON historico_imovel (uf, dia, evento, condicao_nova)",
        """CREATE TABLE IF NOT EXISTS geometria_imovel (
            cod_imovel text PRIMARY KEY, uf text NOT NULL, ibge integer NOT NULL,
            geom geometry(MultiPolygon, 4674) NOT NULL, atualizado_em timestamptz NOT NULL DEFAULT now())""",
        "CREATE INDEX IF NOT EXISTS geometria_imovel_gix ON geometria_imovel USING gist (geom)",
        "CREATE INDEX IF NOT EXISTS geometria_imovel_mun_idx ON geometria_imovel (uf, ibge)",
        "ALTER TABLE sync_estado ADD COLUMN IF NOT EXISTS geometrias_em timestamptz",
        """CREATE TABLE IF NOT EXISTS snapshot_municipio (
            dia date NOT NULL, uf text NOT NULL, ibge integer NOT NULL, condicao_grupo text NOT NULL,
            total integer NOT NULL, PRIMARY KEY (dia, uf, ibge, condicao_grupo))""",
    ):
        conn.execute(statement)
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO indice_perfil (codigo, rotulo, descricao, fonte, peso, grupo, versao)
               VALUES (%(codigo)s, %(rotulo)s, %(descricao)s, %(fonte)s, %(peso)s, %(grupo)s, %(versao)s)
               ON CONFLICT (codigo) DO UPDATE SET rotulo = excluded.rotulo,
                 descricao = excluded.descricao, fonte = excluded.fonte, peso = excluded.peso,
                 grupo = excluded.grupo, versao = excluded.versao""",
            classificacao.catalogo(),
        )


def hash_cadastro(item: dict[str, Any]) -> str:
    """Ignora a data de atualização, que pode mudar em massa sem mudança real."""
    values = [
        item.get(key)
        for key in (
            "ind_status", "ind_tipo", "des_condic", "num_area", "mod_fiscal",
            "municipio", "cod_municipio_ibge", "data_criacao",
        )
    ]
    return hashlib.sha1(json.dumps(values, ensure_ascii=False, default=str).encode()).hexdigest()


def _linha(item: dict[str, Any]) -> tuple[Any, ...] | None:
    if not item.get("cod_imovel") or not item.get("cod_municipio_ibge"):
        return None
    return (
        item["cod_imovel"], item.get("cod_estado"), item.get("municipio") or "",
        item["cod_municipio_ibge"], item.get("ind_status"), item.get("ind_tipo"),
        item.get("des_condic"), item.get("condicao_grupo"), item.get("num_area"),
        item.get("mod_fiscal"), item.get("data_criacao"), item.get("data_atualizacao"),
        hash_cadastro(item),
    )


def gravar_cadastro(
    conn: psycopg.Connection[Any],
    itens: Iterable[dict[str, Any]],
    remover_ibge: tuple[str, int] | None = None,
    historico: bool = False,
    dia: date | None = None,
) -> dict[str, int]:
    """Atualiza imóveis e, em carga completa de município, remove os que sumiram.

    Com `historico`, registra cada imóvel novo, alterado ou removido. A carga inicial não
    registra, porque ainda não existe estado anterior para comparar.
    """
    dia = dia or date.today()
    linhas = {row[0]: row for row in map(_linha, itens) if row}
    columns = ", ".join(COLUNAS)
    with conn.cursor() as cursor:
        cursor.execute(
            f"""CREATE TEMP TABLE entrada_indice ON COMMIT DROP AS
                SELECT {columns} FROM indice_imovel WITH NO DATA"""
        )
        with cursor.copy(f"COPY entrada_indice ({columns}) FROM STDIN") as copy:
            for row in linhas.values():
                copy.write_row(row)
        cursor.execute(
            """SELECT count(*) FILTER (WHERE i.cod_imovel IS NULL) AS novos,
                      count(*) FILTER (WHERE i.hash <> e.hash) AS alterados
               FROM entrada_indice AS e
               LEFT JOIN indice_imovel AS i USING (cod_imovel)"""
        )
        novos, alterados = cursor.fetchone()
        if historico:
            cursor.execute(
                """INSERT INTO historico_imovel (cod_imovel, uf, ibge, dia, evento, condicao_anterior,
                                                 condicao_nova, status_anterior, status_novo)
                   SELECT e.cod_imovel, e.uf, e.ibge, %s,
                          CASE WHEN i.cod_imovel IS NULL THEN 'novo'
                               WHEN i.condicao_grupo IS DISTINCT FROM e.condicao_grupo THEN 'condicao'
                               WHEN i.status IS DISTINCT FROM e.status THEN 'situacao'
                               ELSE 'cadastro' END,
                          i.condicao_grupo, e.condicao_grupo, i.status, e.status
                   FROM entrada_indice AS e LEFT JOIN indice_imovel AS i USING (cod_imovel)
                   WHERE i.cod_imovel IS NULL OR i.hash <> e.hash""",
                (dia,),
            )
        updates = ", ".join(f"{column} = excluded.{column}" for column in COLUNAS[1:])
        cursor.execute(
            f"""INSERT INTO indice_imovel ({columns})
                SELECT {columns} FROM entrada_indice
                ON CONFLICT (cod_imovel) DO UPDATE SET {updates}, visto_em = now(),
                  alterado_em = CASE WHEN indice_imovel.hash <> excluded.hash
                                     THEN now() ELSE indice_imovel.alterado_em END"""
        )
        removidos = 0
        if remover_ibge:
            if historico:
                cursor.execute(
                    """INSERT INTO historico_imovel (cod_imovel, uf, ibge, dia, evento, condicao_anterior, status_anterior)
                       SELECT i.cod_imovel, i.uf, i.ibge, %s, 'removido', i.condicao_grupo, i.status
                       FROM indice_imovel AS i
                       WHERE i.uf = %s AND i.ibge = %s
                         AND NOT EXISTS (SELECT 1 FROM entrada_indice AS e WHERE e.cod_imovel = i.cod_imovel)""",
                    (dia, *remover_ibge),
                )
            cursor.execute(
                """DELETE FROM indice_imovel AS i
                   WHERE i.uf = %s AND i.ibge = %s
                     AND NOT EXISTS (SELECT 1 FROM entrada_indice AS e WHERE e.cod_imovel = i.cod_imovel)""",
                remover_ibge,
            )
            removidos = cursor.rowcount
        cursor.execute("DROP TABLE entrada_indice")
    return {"registros": len(linhas), "novos": novos, "alterados": alterados, "removidos": removidos}


def gravar_geometrias(conn: psycopg.Connection[Any], itens: Iterable[tuple[str, dict[str, Any]]]) -> int:
    """Grava limites simplificados (cerca de 2 m) com índice espacial. Só para imóveis já indexados."""
    with conn.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE entrada_geometria (codigo text, geojson text) ON COMMIT DROP")
        with cursor.copy("COPY entrada_geometria FROM STDIN") as copy:
            for codigo, geometria in itens:
                if codigo and geometria:
                    copy.write_row((codigo, json.dumps(geometria)))
        cursor.execute(
            """INSERT INTO geometria_imovel (cod_imovel, uf, ibge, geom)
               SELECT codigo, uf, ibge, geom FROM (
                   SELECT e.codigo, i.uf, i.ibge,
                          ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SimplifyPreserveTopology(
                              ST_SetSRID(ST_GeomFromGeoJSON(e.geojson), 4674), 0.00002)), 3)) AS geom
                   FROM entrada_geometria AS e JOIN indice_imovel AS i ON i.cod_imovel = e.codigo
               ) AS g WHERE NOT ST_IsEmpty(geom)
               ON CONFLICT (cod_imovel) DO UPDATE SET geom = excluded.geom, uf = excluded.uf,
                 ibge = excluded.ibge, atualizado_em = now()"""
        )
        gravados = cursor.rowcount
        cursor.execute("DROP TABLE entrada_geometria")
    return gravados


def gravar_municipios(conn: psycopg.Connection[Any], uf: str, itens: list[Municipio]) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO municipio_ref (uf, ibge, nome, lon, lat) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (uf, ibge) DO UPDATE SET nome = excluded.nome,
                 lon = excluded.lon, lat = excluded.lat""",
            [(uf, item.ibge, item.nome, item.lon, item.lat) for item in itens],
        )


def gravar_indicadores(
    conn: psycopg.Connection[Any],
    uf: str,
    recompor: set[str],
    sobreposicoes: dict[str, set[str]],
    ibge: int | None = None,
) -> None:
    por_codigo: dict[str, list[str]] = defaultdict(list)
    for campo, codigos in sobreposicoes.items():
        for codigo in codigos:
            por_codigo[codigo].append(campo)
    escopo = "uf = %s" + (" AND ibge = %s" if ibge else "")
    params: tuple[Any, ...] = (uf, ibge) if ibge else (uf,)
    with conn.cursor() as cursor:
        cursor.execute(
            f"""UPDATE indice_imovel SET tem_app_recompor = false, sobreposicoes = '{{}}'
                WHERE {escopo} AND (tem_app_recompor OR sobreposicoes <> '{{}}')""",
            params,
        )
        cursor.execute(
            f"UPDATE indice_imovel SET tem_app_recompor = true WHERE {escopo} AND cod_imovel = ANY(%s)",
            (*params, list(recompor)),
        )
        cursor.executemany(
            "UPDATE indice_imovel SET sobreposicoes = %s WHERE cod_imovel = %s",
            [(sorted(campos), codigo) for codigo, campos in por_codigo.items()],
        )


def gravar_retificacoes(conn: psycopg.Connection[Any], valores: dict[str, int]) -> None:
    if not valores:
        return
    with conn.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE entrada_retificacao (codigo text, total integer) ON COMMIT DROP")
        with cursor.copy("COPY entrada_retificacao FROM STDIN") as copy:
            for row in valores.items():
                copy.write_row(row)
        cursor.execute(
            """UPDATE indice_imovel AS i SET retificacoes = e.total
               FROM entrada_retificacao AS e WHERE e.codigo = i.cod_imovel"""
        )
        cursor.execute("DROP TABLE entrada_retificacao")


class _Acumulador:
    def __init__(self) -> None:
        self.total = 0
        self.area = 0.0
        self.condicoes: Counter[str] = Counter()
        self.status: Counter[str] = Counter()
        self.perfis: Counter[str] = Counter()
        self.faixas: Counter[str] = Counter()
        self.coortes: dict[int, Counter[str]] = defaultdict(Counter)
        self.idades: list[float] = []
        self.prioridade = 0

    def adicionar(self, linha: dict[str, Any], perfis: list[str], prioridade: int, idade: float | None) -> None:
        self.total += 1
        self.area += linha.get("area_ha") or 0
        grupo = linha.get("condicao_grupo") or "outro"
        self.condicoes[grupo] += 1
        self.status[linha.get("status") or "NI"] += 1
        self.perfis.update(perfis)
        self.prioridade += prioridade
        created = linha.get("data_criacao")
        sem_analise = "sem_analise" in perfis
        if created:
            self.coortes[created.year]["total"] += 1
            self.coortes[created.year]["sem_analise"] += int(sem_analise)
        if sem_analise and idade is not None:
            self.idades.append(idade)
            for nome, inicio, fim in FAIXAS:
                if inicio <= idade < fim:
                    self.faixas[nome] += 1
                    break

    def dados(self) -> dict[str, Any]:
        idades = sorted(self.idades)
        sem = self.perfis.get("sem_analise", 0)
        return {
            "total": self.total,
            "area_ha": round(self.area, 2),
            "sem_analise": sem,
            "sem_analise_pct": round(100 * sem / self.total, 1) if self.total else 0,
            "idade_mediana_anos": round(statistics.median(idades), 1) if idades else None,
            "idade_p90_anos": round(idades[int(len(idades) * 0.9)], 1) if idades else None,
            "prioridade_media": round(self.prioridade / self.total, 1) if self.total else 0,
            "condicoes": dict(self.condicoes),
            "status": dict(self.status),
            "perfis": dict(self.perfis),
            "faixas_fila": {nome: self.faixas.get(nome, 0) for nome, _, _ in FAIXAS},
            "coortes": [
                {"ano": ano, **dict(valores)} for ano, valores in sorted(self.coortes.items())
            ],
        }


def recalcular_uf(conn: psycopg.Connection[Any], uf: str, hoje: date | None = None) -> dict[str, int]:
    """Reclassifica a UF e gera resumos e snapshot em uma única leitura do índice."""
    hoje = hoje or date.today()
    estado = _Acumulador()
    municipios: dict[int, _Acumulador] = defaultdict(_Acumulador)
    nomes: dict[int, str] = {}
    mudancas: list[tuple[str, list[str], int]] = []
    with conn.cursor(name="leitura_indice", row_factory=dict_row) as cursor:
        cursor.itersize = 5000
        cursor.execute("SELECT * FROM indice_imovel WHERE uf = %s", (uf,))
        for linha in cursor:
            perfis, prioridade = classificacao.classificar(linha, hoje)
            idade = classificacao.idade_anos(linha, hoje)
            estado.adicionar(linha, perfis, prioridade, idade)
            municipios[linha["ibge"]].adicionar(linha, perfis, prioridade, idade)
            nomes[linha["ibge"]] = linha["municipio"]
            if perfis != linha["perfis"] or prioridade != linha["prioridade"]:
                mudancas.append((linha["cod_imovel"], perfis, prioridade))
    with conn.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE entrada_perfil (codigo text, perfis text[], prioridade integer) ON COMMIT DROP"
        )
        with cursor.copy("COPY entrada_perfil FROM STDIN") as copy:
            for row in mudancas:
                copy.write_row(row)
        cursor.execute(
            """UPDATE indice_imovel AS i SET perfis = e.perfis, prioridade = e.prioridade
               FROM entrada_perfil AS e WHERE e.codigo = i.cod_imovel"""
        )
        cursor.execute("DROP TABLE entrada_perfil")
        cursor.execute("SELECT ibge, nome, lon, lat FROM municipio_ref WHERE uf = %s", (uf,))
        ref = {row[0]: row for row in cursor.fetchall()}
        cursor.execute("DELETE FROM resumo_municipio WHERE uf = %s", (uf,))
        cursor.execute("DELETE FROM snapshot_municipio WHERE uf = %s AND dia = %s", (uf, hoje))
        rows = [(uf, 0, uf, None, None, json.dumps(estado.dados(), ensure_ascii=False))]
        snapshot: list[tuple[Any, ...]] = []
        for ibge, acumulado in municipios.items():
            info = ref.get(ibge)
            rows.append(
                (
                    uf, ibge, info[1] if info else nomes[ibge], info[2] if info else None,
                    info[3] if info else None, json.dumps(acumulado.dados(), ensure_ascii=False),
                )
            )
            snapshot.extend((hoje, uf, ibge, grupo, total) for grupo, total in acumulado.condicoes.items())
        cursor.executemany(
            """INSERT INTO resumo_municipio (uf, ibge, municipio, lon, lat, dados)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            rows,
        )
        cursor.executemany(
            """INSERT INTO snapshot_municipio (dia, uf, ibge, condicao_grupo, total)
               VALUES (%s, %s, %s, %s, %s)""",
            snapshot,
        )
    return {"imoveis": estado.total, "perfis_alterados": len(mudancas), "municipios": len(municipios)}
