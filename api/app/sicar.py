"""Acesso aos serviços públicos do SICAR, com cache que confere se o dado mudou.

Duas fontes oficiais são usadas: o WFS do SICAR (cadastro e limite dos imóveis, por UF)
e o WFS da Consulta Pública (camadas ambientais). O banco local guarda apenas respostas
em cache e métricas; nenhuma cópia permanente da base é necessária.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import weakref
import zlib
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("car.sicar")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://carapp:car-local-only@localhost:55432/car"
)
SICAR_WFS = os.environ.get("SICAR_WFS_URL", "https://geoserver.car.gov.br/geoserver/sicar/wfs")
CONSULTA_WFS = os.environ.get(
    "CONSULTA_WFS_URL", "https://consulta.car.gov.br/geoserver/consulta_publica/wfs"
)
CONSULTA_API = os.environ.get("CONSULTA_API_URL", "https://consulta.car.gov.br/api")
TIMEOUT_SECONDS = float(os.environ.get("SICAR_TIMEOUT_SECONDS", "90"))
MAX_PARALLEL_CALLS = int(os.environ.get("SICAR_MAX_PARALLEL_CALLS", "3"))
MIN_INTERVAL_SECONDS = float(os.environ.get("SICAR_MIN_INTERVAL_SECONDS", "0.1"))
MAX_CACHE_ENTRY_BYTES = 25 * 1024 * 1024

HOUR = 3600
DAY = 24 * HOUR
BRASILIA = timezone(timedelta(hours=-3))
PAGE_LIMIT = 1000
CODE_CHUNK = 200
THEME_CODE_CHUNK = 50

UF_BY_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
UFS = frozenset(UF_BY_IBGE.values())

CONDITION_PATTERNS = {
    "cancelado": "Cancelado%",
    "aguardando_analise": "Aguardando an%lise%",
    "em_analise": "Em an%lise%",
    "analisado_notificacao": "Analisado, aguardando atendimento%",
    "analisado_regularizacao": "Analisado, aguardando regulariza%",
    "analisado_conforme": "Analisado, em conformidade%",
}
CONDITION_GROUPS: dict[str, tuple[str, list[str]]] = {
    "aguardando_analise": ("Aguardando análise", ["aguardando_analise"]),
    "em_analise": ("Em análise", ["em_analise"]),
    "analisado": (
        "Analisado (todos)",
        ["analisado_notificacao", "analisado_regularizacao", "analisado_conforme"],
    ),
    "analisado_notificacao": ("Analisado, aguardando notificação", ["analisado_notificacao"]),
    "analisado_regularizacao": ("Analisado, aguardando regularização", ["analisado_regularizacao"]),
    "analisado_conforme": ("Analisado, em conformidade", ["analisado_conforme"]),
    "cancelado": ("Cancelado", ["cancelado"]),
}

THEME_LABELS = {
    "apps": "Áreas de preservação permanente (APP)",
    "reserva_legal": "Reserva Legal",
    "vegetacao_nativa": "Vegetação nativa",
    "area_consolidada": "Área consolidada",
    "hidrografia": "Hidrografia",
    "area_pousio": "Área de pousio",
    "servidao_administrativa": "Servidão administrativa",
    "uso_restrito": "Uso restrito",
    "ecossistemas_relevo": "Ecossistemas e relevo",
}
RESTORE_LAYERS = [
    "app_escadinha_lago_natural",
    "app_escadinha_nascente_olho_dagua",
    "app_escadinha_rio_10_a_50",
    "app_escadinha_rio_200_a_600",
    "app_escadinha_rio_50_a_200",
    "app_escadinha_rio_acima_600",
    "app_escadinha_rio_ate_10",
    "app_escadinha_vereda",
]
EXTRA_LAYERS = {
    "area_servidao_administrativa_total": "Servidão administrativa total",
    "area_infraestrutura_publica": "Infraestrutura pública",
    "area_utilidade_publica": "Utilidade pública",
    "area_entorno_reservatorio_energia": "Entorno de reservatório de energia",
    "area_uso_restrito_declividade_25_a_45": "Uso restrito por declividade de 25 a 45 graus",
    "area_uso_restrito_pantaneira": "Uso restrito em regiões pantaneiras",
}
OVERLAP_LABELS = {
    "sobreposicao_area_indigena": "O SICAR indica sobreposição com terra indígena",
    "sobreposicao_unidade_conservacao": "O SICAR indica sobreposição com unidade de conservação",
    "sobreposicao_quilombo": "O SICAR indica sobreposição com território quilombola",
    "sobreposicao_area_embargada": "O SICAR indica sobreposição com área embargada",
    "sobreposicao_terras_da_uniao": "O SICAR indica sobreposição com terras da União",
}
ALERT_LABELS = {
    "area_acima_100mil_ha": "Área declarada acima de 100 mil hectares",
    "coordenadas_invalidas": "Polígono com coordenadas inválidas",
    "area_divergente": "Área declarada difere da área calculada pelo polígono",
    **OVERLAP_LABELS,
}
PROPERTY_FIELDS = (
    "cod_imovel,status_imovel,dat_criacao,data_atualizacao,area,condicao,uf,municipio,"
    "cod_municipio_ibge,m_fiscal,tipo_imovel"
)

pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=int(os.environ.get("DB_POOL_MAX_SIZE", "6")),
    timeout=10,
    open=False,
    kwargs={
        "row_factory": dict_row,
        "connect_timeout": 5,
        "options": f"-c statement_timeout={os.environ.get('DB_STATEMENT_TIMEOUT_MS', '15000')}",
    },
)


class UpstreamError(Exception):
    """O serviço oficial não respondeu de forma utilizável."""


class InvalidFilter(ValueError):
    """Um filtro não corresponde a dados conhecidos."""


# ---------------------------------------------------------------------------
# Cache e métricas
# ---------------------------------------------------------------------------

def ensure_schema() -> None:
    with pool.connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sicar_cache (
                chave text PRIMARY KEY,
                descricao text NOT NULL,
                versao text,
                dados bytea NOT NULL,
                tamanho integer NOT NULL,
                custo_chamadas integer NOT NULL DEFAULT 0,
                custo_bytes bigint NOT NULL DEFAULT 0,
                criado_em timestamptz NOT NULL DEFAULT now(),
                expira_em timestamptz NOT NULL,
                acessos bigint NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS sicar_cache_expira_idx ON sicar_cache (expira_em)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sicar_metricas (
                id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                desde timestamptz NOT NULL DEFAULT now(),
                chamadas bigint NOT NULL DEFAULT 0,
                bytes_recebidos bigint NOT NULL DEFAULT 0,
                falhas bigint NOT NULL DEFAULT 0,
                cache_acertos bigint NOT NULL DEFAULT 0,
                cache_faltas bigint NOT NULL DEFAULT 0,
                respostas_antigas bigint NOT NULL DEFAULT 0,
                chamadas_evitadas bigint NOT NULL DEFAULT 0,
                bytes_evitados bigint NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("INSERT INTO sicar_metricas (id) VALUES (1) ON CONFLICT DO NOTHING")


METRIC_COLUMNS = {
    "chamadas", "bytes_recebidos", "falhas", "cache_acertos", "cache_faltas",
    "respostas_antigas", "chamadas_evitadas", "bytes_evitados",
}


def add_metrics(**values: int) -> None:
    fields = {key: value for key, value in values.items() if key in METRIC_COLUMNS and value}
    if not fields:
        return
    assignments = ", ".join(f"{key} = {key} + %({key})s" for key in fields)
    try:
        with pool.connection() as conn:
            conn.execute(f"UPDATE sicar_metricas SET {assignments} WHERE id = 1", fields)
    except psycopg.Error:
        log.warning("Falha ao registrar métricas", exc_info=True)


def metrics() -> dict[str, Any]:
    with pool.connection() as conn:
        row = conn.execute("SELECT * FROM sicar_metricas WHERE id = 1").fetchone()
        cache = conn.execute(
            "SELECT count(*) AS entradas, coalesce(sum(tamanho), 0) AS bytes FROM sicar_cache"
        ).fetchone()
    answered = row["cache_acertos"] + row["cache_faltas"]
    would_call = row["chamadas"] + row["chamadas_evitadas"]
    return {
        "desde": row["desde"].isoformat(),
        "chamadas_ao_sicar": row["chamadas"],
        "bytes_recebidos_do_sicar": row["bytes_recebidos"],
        "falhas_do_sicar": row["falhas"],
        "consultas_respondidas": answered,
        "respondidas_pelo_cache": row["cache_acertos"],
        "respostas_antigas_por_falha": row["respostas_antigas"],
        "chamadas_evitadas": row["chamadas_evitadas"],
        "bytes_evitados": row["bytes_evitados"],
        "reducao_de_chamadas_pct": (
            round(100 * row["chamadas_evitadas"] / would_call, 1) if would_call else 0
        ),
        "cache": {"entradas": cache["entradas"], "bytes": cache["bytes"]},
    }


_cost = threading.local()
_key_locks: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
_key_locks_guard = threading.Lock()


class _LockHolder:
    """Objeto referenciável por weakref que carrega a trava de uma chave."""

    def __init__(self) -> None:
        self.lock = threading.Lock()


def _lock_for(key: str) -> _LockHolder:
    with _key_locks_guard:
        holder = _key_locks.get(key)
        if holder is None:
            holder = _LockHolder()
            _key_locks[key] = holder  # type: ignore[assignment]
        return holder  # type: ignore[return-value]


def _track(calls: int, size: int) -> None:
    for frame in getattr(_cost, "frames", []):
        frame[0] += calls
        frame[1] += size


def _pack(value: Any) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return zlib.compress(raw.encode("utf-8"), 6)


def _unpack(value: bytes) -> Any:
    return json.loads(zlib.decompress(bytes(value)))


def _key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_entry(key: str) -> dict[str, Any] | None:
    try:
        with pool.connection() as conn:
            return conn.execute(
                """SELECT dados, versao, custo_chamadas, custo_bytes,
                          expira_em > now() AS valido
                   FROM sicar_cache WHERE chave = %s""",
                (key,),
            ).fetchone()
    except psycopg.Error:
        log.warning("Falha ao ler o cache", exc_info=True)
        return None


def _write_entry(
    key: str, label: str, version: str | None, packed: bytes, calls: int, size: int, ttl: int
) -> None:
    if len(packed) > MAX_CACHE_ENTRY_BYTES:
        return
    try:
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO sicar_cache
                    (chave, descricao, versao, dados, tamanho, custo_chamadas, custo_bytes, expira_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(secs => %s))
                ON CONFLICT (chave) DO UPDATE SET
                    descricao = excluded.descricao, versao = excluded.versao,
                    dados = excluded.dados, tamanho = excluded.tamanho,
                    custo_chamadas = excluded.custo_chamadas, custo_bytes = excluded.custo_bytes,
                    criado_em = now(), expira_em = excluded.expira_em
                """,
                (key, label, version, packed, len(packed), calls, size, ttl),
            )
    except psycopg.Error:
        log.warning("Falha ao gravar o cache", exc_info=True)


def _register_hit(key: str, entry: dict[str, Any]) -> None:
    add_metrics(
        cache_acertos=1,
        chamadas_evitadas=entry["custo_chamadas"],
        bytes_evitados=entry["custo_bytes"],
    )
    try:
        with pool.connection() as conn:
            conn.execute("UPDATE sicar_cache SET acessos = acessos + 1 WHERE chave = %s", (key,))
    except psycopg.Error:
        log.warning("Falha ao contar acesso do cache", exc_info=True)


def cached(
    label: str,
    key_parts: Iterable[Any],
    ttl: int,
    producer: Callable[[], Any],
    version: str | None = None,
    version_known: bool = True,
    internal: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Devolve o valor guardado se ainda vale; senão busca uma única vez no SICAR.

    Se o SICAR falhar e houver uma cópia anterior, ela é devolvida e marcada como antiga.
    Consultas internas de apoio não contam como economia: sem cache elas nem existiriam.
    """
    key = _key(label, *key_parts)

    def hit(item: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if not internal:
            _register_hit(key, item)
        return _unpack(item["dados"]), {"origem": "cache", "chamadas_sicar": 0}

    def fresh(entry: dict[str, Any] | None) -> bool:
        if not entry:
            return False
        if not version_known:
            return True
        return bool(entry["valido"]) and entry["versao"] == version

    entry = _read_entry(key)
    if fresh(entry):
        assert entry is not None
        return hit(entry)

    holder = _lock_for(key)
    with holder.lock:
        entry = _read_entry(key)
        if fresh(entry):
            assert entry is not None
            return hit(entry)

        frames = getattr(_cost, "frames", None)
        if frames is None:
            frames = _cost.frames = []
        frame = [0, 0]
        frames.append(frame)
        try:
            value = producer()
        except UpstreamError:
            if entry:
                add_metrics(respostas_antigas=1)
                return _unpack(entry["dados"]), {"origem": "cache_antigo", "chamadas_sicar": frame[0]}
            raise
        finally:
            frames.pop()

        if not internal:
            add_metrics(cache_faltas=1)
        _write_entry(key, label, version, _pack(value), frame[0], frame[1], ttl)
        return value, {"origem": "sicar", "chamadas_sicar": frame[0]}


def cached_many(
    label: str,
    items: list[str],
    ttl: int,
    fetch: Callable[[list[str]], dict[str, Any]],
    version: str | None = None,
    chunk: int = CODE_CHUNK,
) -> dict[str, Any]:
    """Versão por item: busca no SICAR apenas os itens que ainda não estão guardados."""
    if not items:
        return {}
    keys = {item: _key(label, item) for item in items}
    found: dict[str, Any] = {}
    saved_bytes = 0
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT chave, dados, custo_chamadas, custo_bytes FROM sicar_cache
                   WHERE chave = ANY(%s) AND expira_em > now()
                     AND versao IS NOT DISTINCT FROM %s""",
                (list(keys.values()), version),
            ).fetchall()
        by_key = {row["chave"]: row for row in rows}
        for item, key in keys.items():
            row = by_key.get(key)
            if row:
                found[item] = _unpack(row["dados"])
                saved_bytes += row["custo_bytes"]
    except psycopg.Error:
        log.warning("Falha ao ler o cache em lote", exc_info=True)

    missing = [item for item in items if item not in found]
    add_metrics(
        cache_acertos=len(found),
        cache_faltas=len(missing),
        # Cada chamada oficial atende um bloco de itens; conta só os blocos poupados.
        chamadas_evitadas=-(-len(found) // chunk),
        bytes_evitados=saved_bytes,
    )
    if not missing:
        return found

    frames = getattr(_cost, "frames", None)
    if frames is None:
        frames = _cost.frames = []
    frame = [0, 0]
    frames.append(frame)
    try:
        fetched = fetch(missing)
    finally:
        frames.pop()

    share_bytes = frame[1] // max(len(missing), 1)
    for item in missing:
        if item in fetched:
            found[item] = fetched[item]
            _write_entry(
                keys[item], label, version, _pack(fetched[item]), 0, share_bytes, ttl
            )
    return found


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------

_gate = threading.BoundedSemaphore(MAX_PARALLEL_CALLS)
_pace_lock = threading.Lock()
_next_call_at = 0.0


def _tls_context() -> ssl.SSLContext:
    """Aceita a suíte TLS antiga dos servidores oficiais, mantendo a validação do certificado."""
    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    return context


TLS_CONTEXT = _tls_context()


def _pace() -> None:
    global _next_call_at
    with _pace_lock:
        now = time.monotonic()
        wait = max(0.0, _next_call_at - now)
        _next_call_at = max(now, _next_call_at) + MIN_INTERVAL_SECONDS
    if wait:
        time.sleep(wait)


def _http(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "car-em-recorte/0.4", "Accept-Encoding": "gzip"},
    )
    last_error: Exception | None = None
    with _gate:
        for attempt in range(3):
            _pace()
            try:
                with urllib.request.urlopen(
                    request, timeout=TIMEOUT_SECONDS, context=TLS_CONTEXT
                ) as response:
                    raw = response.read()
                    encoded = response.headers.get("Content-Encoding") == "gzip"
                add_metrics(chamadas=1, bytes_recebidos=len(raw))
                _track(1, len(raw))
                return gzip.decompress(raw) if encoded else raw
            except urllib.error.HTTPError as exc:
                last_error = exc
                add_metrics(chamadas=1, falhas=1)
                _track(1, 0)
                if exc.code < 500 and exc.code != 429:
                    break
            except (OSError, TimeoutError) as exc:
                last_error = exc
                add_metrics(chamadas=1, falhas=1)
                _track(1, 0)
            time.sleep(0.8 * (attempt + 1))
    raise UpstreamError(f"Falha ao consultar {url.split('?')[0]}: {last_error}")


def _wfs_raw(url: str, params: dict[str, Any]) -> bytes:
    payload = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", **params}
    return _http(url, urllib.parse.urlencode(payload).encode("utf-8"))


def wfs(url: str, **params: Any) -> dict[str, Any]:
    body = _wfs_raw(url, {"outputFormat": "application/json", "srsName": "EPSG:4326", **params})
    try:
        result = json.loads(body)
    except ValueError as exc:
        raise UpstreamError(f"Resposta inesperada do WFS: {body[:200]!r}") from exc
    if "features" not in result:
        raise UpstreamError("O WFS respondeu sem a lista de feições.")
    return result


def wfs_hits(url: str, type_name: str, cql: str | None = None) -> int:
    params: dict[str, Any] = {"typeNames": type_name, "resultType": "hits"}
    if cql:
        params["cql_filter"] = cql
    match = re.search(rb'numberMatched="(\d+)"', _wfs_raw(url, params))
    if not match:
        raise UpstreamError("O WFS não informou a quantidade de registros.")
    return int(match.group(1))


def consulta_api(path: str) -> Any:
    body = _http(f"{CONSULTA_API}/{path}")
    try:
        return json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# Referências
# ---------------------------------------------------------------------------

def plain(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def property_layer(uf: str) -> str:
    return f"sicar:sicar_imoveis_{uf.lower()}"


def check_uf(uf: str) -> str:
    value = uf.strip().upper()
    if value not in UFS:
        raise InvalidFilter("Estado inválido.")
    return value


def states() -> list[dict[str, Any]]:
    regions, _ = cached(
        "regioes", [], 7 * DAY, lambda: consulta_api("geoServices/getRegions"), internal=True
    )
    items = [
        {"uf": state["id"], "nome": state["name"], "regiao": region["name"]}
        for region in regions
        for state in region.get("states", [])
    ]
    return sorted(items, key=lambda item: plain(item["nome"]))


def _bounds(polygon: str | None) -> list[float] | None:
    numbers = [float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", polygon or "")]
    if len(numbers) < 4:
        return None
    xs, ys = numbers[0::2], numbers[1::2]
    return [min(xs), min(ys), max(xs), max(ys)]


def municipalities(uf: str) -> list[dict[str, Any]]:
    uf = check_uf(uf)

    def load() -> list[dict[str, Any]]:
        rows = consulta_api(f"state/getCitiesByUf/{uf}")
        return [
            {"name": row["name"], "ibge": row["id"], "bounds": _bounds(row.get("bounderBox"))}
            for row in rows
        ]

    items, _ = cached("municipios", [uf], 7 * DAY, load, internal=True)
    return sorted(items, key=lambda item: plain(item["name"]))


def find_municipality(uf: str, name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    wanted = plain(name)
    for item in municipalities(uf):
        if plain(item["name"]) == wanted:
            return item
    raise InvalidFilter(f"Município não encontrado em {uf}.")


def br_day(value: str | None) -> date | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(BRASILIA).date()


def theme_version() -> tuple[str | None, bool]:
    """Identifica a última carga da Consulta Pública, que alimenta as camadas ambientais."""
    try:
        value, meta = cached(
            "versao_camadas", [], 600, lambda: consulta_api("batchJob/getLastEndTime"),
            internal=True,
        )
    except UpstreamError:
        return None, False
    return str(value), meta["origem"] != "cache_antigo"


def fingerprint(uf: str, ibge: int | None = None) -> dict[str, Any] | None:
    """Total e data mais recente do recorte: mudam quando o SICAR altera os imóveis."""

    def load() -> dict[str, Any]:
        cql = "data_atualizacao IS NOT NULL"
        if ibge:
            cql = f"cod_municipio_ibge={int(ibge)} AND {cql}"
        result = wfs(
            SICAR_WFS,
            typeNames=property_layer(uf),
            count=1,
            sortBy="data_atualizacao D",
            propertyName="cod_imovel,data_atualizacao",
            cql_filter=cql,
        )
        features = result["features"]
        latest = features[0]["properties"].get("data_atualizacao") if features else None
        return {"total": result.get("numberMatched", 0), "ultima": latest}

    try:
        value, _ = cached("impressao", [uf, ibge], 600, load, internal=True)
    except UpstreamError:
        return None
    return value


# ---------------------------------------------------------------------------
# Imóveis
# ---------------------------------------------------------------------------

def condition_group(text: str | None) -> str:
    value = plain(text)
    rules = [
        ("cancelado", "cancelado"),
        ("aguardando analise", "aguardando_analise"),
        ("em analise", "em_analise"),
        ("analisado, aguardando atendimento", "analisado_notificacao"),
        ("analisado, aguardando regularizacao", "analisado_regularizacao"),
        ("analisado, em conformidade", "analisado_conforme"),
    ]
    return next((group for prefix, group in rules if value.startswith(prefix)), "outro")


def _coordinates_valid(geometry: dict[str, Any] | None) -> bool:
    if not geometry:
        return True

    def walk(item: Any) -> bool:
        if item and isinstance(item[0], (int, float)):
            return -180 <= item[0] <= 180 and -90 <= item[1] <= 90
        return all(walk(child) for child in item)

    return walk(geometry.get("coordinates", []))


def normalize_property(feature: dict[str, Any]) -> dict[str, Any]:
    p = feature["properties"]
    created, updated = br_day(p.get("dat_criacao")), br_day(p.get("data_atualizacao"))
    alerts = []
    if (p.get("area") or 0) > 100000:
        alerts.append("area_acima_100mil_ha")
    if not _coordinates_valid(feature.get("geometry")):
        alerts.append("coordenadas_invalidas")
    return {
        "cod_imovel": p.get("cod_imovel"),
        "municipio": p.get("municipio"),
        "cod_municipio_ibge": p.get("cod_municipio_ibge"),
        "cod_estado": p.get("uf"),
        "ind_status": p.get("status_imovel"),
        "ind_tipo": p.get("tipo_imovel"),
        "num_area": p.get("area"),
        "mod_fiscal": p.get("m_fiscal"),
        "des_condic": p.get("condicao"),
        "condicao_grupo": condition_group(p.get("condicao")),
        "dat_criaca": created.strftime("%d/%m/%Y") if created else None,
        "dat_atuali": updated.strftime("%d/%m/%Y") if updated else None,
        "data_criacao": created.isoformat() if created else None,
        "data_atualizacao": updated.isoformat() if updated else None,
        "origem": "sicar",
        "alertas": alerts,
    }


def _property_feature(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature.get("id"),
        "geometry": feature.get("geometry"),
        "properties": normalize_property(feature),
    }


def layers_for_code(code: str) -> list[str]:
    """A UF real vem do código IBGE; o prefixo pode divergir em imóveis de divisa."""
    parts = code.split("-")
    candidates = [UF_BY_IBGE.get(parts[1][:2]) if len(parts) > 1 else None, parts[0]]
    return list(dict.fromkeys(uf for uf in candidates if uf in UFS))


def _codes_cql(codes: list[str]) -> str:
    return "cod_imovel IN (" + ",".join(quote(code) for code in codes) + ")"


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def get_property(code: str) -> dict[str, Any] | None:
    def load() -> dict[str, Any] | None:
        for uf in layers_for_code(code):
            result = wfs(
                SICAR_WFS,
                typeNames=property_layer(uf),
                cql_filter=f"cod_imovel={quote(code)}",
                count=5,
            )
            if result["features"]:
                return _property_feature(result["features"][0])
        return None

    value, _ = cached("imovel_completo", [code], HOUR, load)
    return value


def get_properties(codes: list[str]) -> dict[str, dict[str, Any]]:
    def fetch(missing: list[str]) -> dict[str, Any]:
        by_uf: dict[str, list[str]] = {}
        for code in missing:
            for uf in layers_for_code(code)[:1]:
                by_uf.setdefault(uf, []).append(code)
        found: dict[str, Any] = {}
        for uf, group in by_uf.items():
            for chunk in _chunks(group, CODE_CHUNK):
                result = wfs(
                    SICAR_WFS,
                    typeNames=property_layer(uf),
                    propertyName=PROPERTY_FIELDS,
                    cql_filter=_codes_cql(chunk),
                    count=len(chunk) + 5,
                )
                for feature in result["features"]:
                    item = normalize_property(feature)
                    found[item["cod_imovel"]] = item
        # Imóveis de divisa podem estar na camada indicada pelo prefixo do código.
        for code in [item for item in missing if item not in found]:
            for uf in layers_for_code(code)[1:]:
                result = wfs(
                    SICAR_WFS,
                    typeNames=property_layer(uf),
                    propertyName=PROPERTY_FIELDS,
                    cql_filter=f"cod_imovel={quote(code)}",
                    count=2,
                )
                if result["features"]:
                    found[code] = normalize_property(result["features"][0])
        return found

    return cached_many("imovel_cadastro", codes, HOUR, fetch)


# ---------------------------------------------------------------------------
# Camadas ambientais
# ---------------------------------------------------------------------------

def theme_catalog() -> dict[str, dict[str, str]]:
    """Mapeia cada camada oficial para o grupo mostrado na aplicação."""

    def load() -> list[list[str]]:
        data = consulta_api("map/getLayers")
        rows: list[list[str]] = []
        for group in data.get("groups", []):
            if group.get("name") == "Imóveis Rurais declarados":
                continue
            for layer in group.get("layers", []):
                has_code = any(
                    option.get("filter") == "cod_imovel" for option in layer.get("options", [])
                )
                if has_code and str(layer.get("layers", "")).startswith("consulta_publica:"):
                    rows.append([layer["layers"].split(":", 1)[1], layer.get("name", "")])
        return rows

    rows, _ = cached("catalogo_camadas", [], DAY, load, internal=True)
    catalog = {name: {"rotulo": label, "camada": _theme_group(name)} for name, label in rows}
    for name, label in EXTRA_LAYERS.items():
        catalog.setdefault(name, {"rotulo": label, "camada": _theme_group(name)})
    return catalog


def _theme_group(name: str) -> str:
    if name.startswith("app_"):
        return "apps"
    if name.startswith("arl_"):
        return "reserva_legal"
    if name in {"vegetacao_nativa", "area_consolidada", "area_pousio"}:
        return name
    if name.startswith("area_uso_restrito"):
        return "uso_restrito"
    if name in {
        "area_servidao_administrativa_total", "area_infraestrutura_publica",
        "area_utilidade_publica", "area_entorno_reservatorio_energia",
    }:
        return "servidao_administrativa"
    if name.startswith(("rio_", "reservatorio_")) or name in {
        "nascente_olho_dagua", "lago_natural", "vereda",
    }:
        return "hidrografia"
    return "ecossistemas_relevo"


def _multi_query(names: list[str]) -> str:
    return "".join(f"(consulta_publica:{name})" for name in names)


def _layer_of(feature: dict[str, Any]) -> str:
    return str(feature.get("id", "")).rsplit(".", 1)[0]


def _theme_features(code: str) -> list[dict[str, Any]]:
    names = list(theme_catalog())
    condition = f"cod_imovel={quote(code)}"
    return wfs(
        CONSULTA_WFS,
        typeNames=_multi_query(names),
        cql_filter=";".join([condition] * len(names)),
    )["features"]


def _areas(groups: list[dict[str, Any]]) -> dict[str, float]:
    """Calcula áreas no PostGIS, unindo polígonos para não contar sobreposições duas vezes."""
    if not groups:
        return {}
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """
                WITH f AS (
                    SELECT k.chave,
                           ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(x->>'g'), 4326)) AS g
                    FROM jsonb_array_elements(%s::jsonb) AS x
                    CROSS JOIN LATERAL jsonb_array_elements_text(x->'k') AS k(chave)
                )
                SELECT chave,
                       ST_Area(ST_CollectionExtract(ST_Union(g), 3)::geography) / 10000.0 AS ha
                FROM f GROUP BY chave
                """,
                (json.dumps(groups),),
            ).fetchall()
        return {row["chave"]: round(row["ha"], 4) for row in rows if row["ha"]}
    except psycopg.Error:
        log.warning("Falha ao calcular áreas", exc_info=True)
        return {}


def property_themes(code: str, geometry: dict[str, Any] | None, updated: str | None) -> dict[str, Any]:
    version, known = theme_version()

    def load() -> dict[str, Any]:
        catalog = theme_catalog()
        features = _theme_features(code)
        counts: dict[str, int] = {}
        official: dict[str, float] = {}
        payload: list[dict[str, Any]] = []
        for feature in features:
            layer = _layer_of(feature)
            counts[layer] = counts.get(layer, 0) + 1
            # A camada oficial traz a área de cada feição, quando ela foi calculada no SICAR.
            official[layer] = official.get(layer, 0.0) + (
                feature["properties"].get("nu_area_imovel") or 0
            )
            if not feature.get("geometry"):
                continue
            keys = [layer]
            if layer in RESTORE_LAYERS:
                keys.append("__recompor")
            elif catalog.get(layer, {}).get("camada") == "apps":
                keys.append("__app_total")
            payload.append({"k": keys, "g": json.dumps(feature["geometry"])})
        if geometry and _coordinates_valid(geometry):
            payload.append({"k": ["__imovel"], "g": json.dumps(geometry)})
        areas = _areas(payload)
        rows = [
            {
                "camada": catalog.get(layer, {}).get("camada", "ecossistemas_relevo"),
                "categoria": catalog.get(layer, {}).get("rotulo", layer),
                "feicoes": total,
                "area_ha": round(official[layer], 4) if official[layer] > 0 else areas.get(layer),
            }
            for layer, total in counts.items()
        ]
        if "__app_total" in areas:
            rows.append(
                {
                    "camada": "apps",
                    "categoria": "APP total, sem contar sobreposições",
                    "feicoes": sum(
                        total for layer, total in counts.items()
                        if layer.startswith("app_") and layer not in RESTORE_LAYERS
                    ),
                    "area_ha": areas["__app_total"],
                }
            )
        rows.sort(key=lambda row: (row["camada"], row["categoria"]))
        return {
            "linhas": rows,
            "app_a_recompor_ha": areas.get("__recompor", 0),
            "area_calculada_ha": areas.get("__imovel"),
            "features": [
                {
                    "type": "Feature",
                    "id": feature.get("id"),
                    "geometry": feature.get("geometry"),
                    "properties": {
                        "camada_oficial": _layer_of(feature),
                        "camada": catalog.get(_layer_of(feature), {}).get("camada"),
                        "categoria": catalog.get(_layer_of(feature), {}).get("rotulo"),
                        "cod_imovel": code,
                    },
                }
                for feature in features
            ],
        }

    value, _ = cached(
        "temas_imovel", [code, updated], 7 * DAY, load, version=version, version_known=known
    )
    return value


def theme_counts(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Conta feições por camada para vários imóveis, sem transferir geometrias."""
    version, _ = theme_version()

    def fetch(missing: list[str]) -> dict[str, Any]:
        catalog = theme_catalog()
        names = list(catalog)
        result: dict[str, Any] = {code: {"camadas": {}, "recompor": 0} for code in missing}
        for chunk in _chunks(missing, THEME_CODE_CHUNK):
            condition = _codes_cql(chunk)
            features = wfs(
                CONSULTA_WFS,
                typeNames=_multi_query(names),
                propertyName="cod_imovel",
                cql_filter=";".join([condition] * len(names)),
            )["features"]
            for feature in features:
                code = feature["properties"].get("cod_imovel")
                if code not in result:
                    continue
                layer = _layer_of(feature)
                group = catalog.get(layer, {}).get("camada", "ecossistemas_relevo")
                result[code]["camadas"][group] = result[code]["camadas"].get(group, 0) + 1
                if layer in RESTORE_LAYERS:
                    result[code]["recompor"] += 1
        return result

    return cached_many(
        "temas_contagem", codes, 7 * DAY, fetch, version=version, chunk=THEME_CODE_CHUNK
    )


def overlaps(codes_by_type: dict[str, list[str]]) -> dict[str, list[str]]:
    """Lê os indicadores oficiais de sobreposição dos imóveis informados."""
    found: dict[str, list[str]] = {}
    layer_by_type = {"IRU": "iru", "AST": "ast", "PCT": "pct"}
    fields = ",".join(["cod_imovel", *OVERLAP_LABELS])
    for kind, codes in codes_by_type.items():
        layer = layer_by_type.get(kind)
        if not layer or not codes:
            continue

        def fetch(missing: list[str]) -> dict[str, Any]:
            result: dict[str, Any] = {code: [] for code in missing}
            for chunk in _chunks(missing, CODE_CHUNK):
                features = wfs(
                    CONSULTA_WFS,
                    typeNames=f"consulta_publica:{layer}",
                    propertyName=fields,
                    cql_filter=_codes_cql(chunk),
                    count=len(chunk) + 5,
                )["features"]
                for feature in features:
                    p = feature["properties"]
                    if p.get("cod_imovel") in result:
                        result[p["cod_imovel"]] = [
                            key for key in OVERLAP_LABELS if (p.get(key) or 0) > 0
                        ]
            return result

        try:
            found.update(cached_many(f"sobreposicoes_{layer}", codes, DAY, fetch))
        except UpstreamError:
            log.warning("Sobreposições indisponíveis para %s", layer)
    return found


# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SearchFilters:
    uf: str = "MA"
    municipality: str | None = None
    ibge: int | None = None
    status: str | None = None
    condition: str | None = None
    updated_since: str | None = None
    app_to_restore: bool = False
    area_min: float | None = None
    area_max: float | None = None
    bbox: tuple[float, float, float, float] | None = None


def _condition_cql(column: str, condition: str) -> str:
    groups = CONDITION_GROUPS[condition][1]
    return "(" + " OR ".join(
        f"{column} ILIKE {quote(CONDITION_PATTERNS[group])}" for group in groups
    ) + ")"


def property_cql(filters: SearchFilters) -> str | None:
    clauses: list[str] = []
    if filters.ibge:
        clauses.append(f"cod_municipio_ibge={int(filters.ibge)}")
    if filters.status:
        clauses.append(f"status_imovel={quote(filters.status)}")
    if filters.condition:
        clauses.append(_condition_cql("condicao", filters.condition))
    if filters.updated_since:
        clauses.append(f"data_atualizacao >= {quote(filters.updated_since)}")
    if filters.area_min is not None:
        clauses.append(f"area >= {float(filters.area_min)}")
    if filters.area_max is not None:
        clauses.append(f"area <= {float(filters.area_max)}")
    if filters.bbox:
        west, south, east, north = (float(value) for value in filters.bbox)
        clauses.append(f"BBOX(geo_area_imovel,{west},{south},{east},{north},'EPSG:4326')")
    return " AND ".join(clauses) or None


def _theme_filter(filters: SearchFilters) -> str:
    clauses = [f"uf={quote(filters.uf)}"]
    if filters.municipality:
        clauses.append(f"municipio={quote(filters.municipality)}")
    if filters.status:
        clauses.append(f"status_imovel={quote(filters.status)}")
    if filters.condition:
        clauses.append(_condition_cql("situacao_analise", filters.condition))
    if filters.updated_since:
        clauses.append(f"dt_atualizacao >= {quote(filters.updated_since)}")
    return " AND ".join(clauses)


def _search_version(filters: SearchFilters) -> tuple[str | None, bool, int]:
    if filters.ibge:
        mark = fingerprint(filters.uf, filters.ibge)
        if mark is None:
            return None, False, 6 * HOUR
        return f"{mark['total']}:{mark['ultima']}", True, 6 * HOUR
    return None, True, HOUR


def restore_codes(filters: SearchFilters) -> list[str]:
    """Imóveis com APP a recompor, combinando as oito camadas oficiais."""
    base = SearchFilters(
        uf=filters.uf, municipality=filters.municipality, ibge=filters.ibge,
        status=filters.status, condition=filters.condition, updated_since=filters.updated_since,
    )
    version, known = theme_version()

    def load_base() -> list[str]:
        condition = _theme_filter(base)
        features = wfs(
            CONSULTA_WFS,
            typeNames=_multi_query(RESTORE_LAYERS),
            propertyName="cod_imovel",
            cql_filter=";".join([condition] * len(RESTORE_LAYERS)),
        )["features"]
        return sorted({f["properties"]["cod_imovel"] for f in features if f["properties"].get("cod_imovel")})

    codes, _ = cached(
        "codigos_recompor", [asdict(base)], DAY, load_base, version=version, version_known=known
    )
    if filters.area_min is None and filters.area_max is None and not filters.bbox:
        return codes

    def refine() -> list[str]:
        spatial = SearchFilters(
            uf=filters.uf, area_min=filters.area_min, area_max=filters.area_max, bbox=filters.bbox
        )
        extra = property_cql(spatial)
        matched: set[str] = set()
        for chunk in _chunks(codes, CODE_CHUNK):
            features = wfs(
                SICAR_WFS,
                typeNames=property_layer(filters.uf),
                propertyName="cod_imovel",
                cql_filter=f"{_codes_cql(chunk)} AND {extra}",
                count=len(chunk) + 5,
            )["features"]
            matched.update(feature["properties"]["cod_imovel"] for feature in features)
        return sorted(matched)

    refined, _ = cached(
        "codigos_recompor_refinados", [asdict(filters)], HOUR, refine,
        version=version, version_known=known,
    )
    return refined


def _features_by_codes(uf: str, codes: list[str], geometry: bool) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for chunk in _chunks(codes, CODE_CHUNK):
        params: dict[str, Any] = {} if geometry else {"propertyName": PROPERTY_FIELDS}
        result = wfs(
            SICAR_WFS,
            typeNames=property_layer(uf),
            cql_filter=_codes_cql(chunk),
            count=len(chunk) + 5,
            sortBy="cod_imovel",
            **params,
        )
        collected.extend(_property_feature(feature) for feature in result["features"])
    return collected


def search(filters: SearchFilters, page: int, page_size: int) -> tuple[dict[str, Any], dict[str, Any]]:
    version, known, ttl = _search_version(filters)

    def load() -> dict[str, Any]:
        offset = (page - 1) * page_size
        if filters.app_to_restore:
            codes = restore_codes(filters)
            selected = codes[offset:offset + page_size]
            return {
                "total": len(codes),
                "features": _features_by_codes(filters.uf, selected, True) if selected else [],
            }
        params: dict[str, Any] = {}
        cql = property_cql(filters)
        if cql:
            params["cql_filter"] = cql
        result = wfs(
            SICAR_WFS,
            typeNames=property_layer(filters.uf),
            count=page_size,
            startIndex=offset,
            sortBy="cod_imovel",
            **params,
        )
        return {
            "total": result.get("numberMatched", 0),
            "features": [_property_feature(feature) for feature in result["features"]],
        }

    return cached(
        "busca", [asdict(filters), page, page_size], ttl, load, version=version, version_known=known
    )


def export(filters: SearchFilters, geometry: bool, total: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    version, known, ttl = _search_version(filters)

    def load() -> list[dict[str, Any]]:
        if filters.app_to_restore:
            return _features_by_codes(filters.uf, restore_codes(filters), geometry)
        collected: list[dict[str, Any]] = []
        params: dict[str, Any] = {} if geometry else {"propertyName": PROPERTY_FIELDS}
        cql = property_cql(filters)
        if cql:
            params["cql_filter"] = cql
        while len(collected) < total:
            result = wfs(
                SICAR_WFS,
                typeNames=property_layer(filters.uf),
                count=PAGE_LIMIT,
                startIndex=len(collected),
                sortBy="cod_imovel",
                **params,
            )
            if not result["features"]:
                break
            collected.extend(_property_feature(feature) for feature in result["features"])
        return collected

    return cached(
        "exportacao", [asdict(filters), geometry], ttl, load, version=version, version_known=known
    )


def condition_counts(uf: str) -> dict[str, int]:
    def load() -> dict[str, int]:
        return {
            key: wfs_hits(SICAR_WFS, property_layer(uf), _condition_cql("condicao", key))
            for key in CONDITION_GROUPS
        }

    value, _ = cached("contagem_condicoes", [uf], 6 * HOUR, load)
    return value
