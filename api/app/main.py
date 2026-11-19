from __future__ import annotations

import csv
import io
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import indice, rotas_radar, sicar
from .sicar import ALERT_LABELS, CONDITION_GROUPS, THEME_LABELS, InvalidFilter, SearchFilters, UpstreamError

BATCH_LIMIT = 1000
EXPORT_LIMIT = 10000
CAR_CODE = re.compile(r"^[A-Z]{2}-[0-9]{7}-[A-Z0-9.]{8,64}$")
VALID_STATUSES = {"AT", "PE", "CA", "SU"}
STATUS_LABELS = {"AT": "Ativo", "PE": "Pendente", "CA": "Cancelado", "SU": "Suspenso"}
SOURCE = "Serviços públicos do SICAR, consultados ao vivo"
EXPORT_COLUMNS = [
    ("cod_imovel", "codigo_car"),
    ("municipio", "municipio"),
    ("cod_estado", "uf"),
    ("ind_status", "situacao"),
    ("ind_tipo", "tipo_imovel"),
    ("num_area", "area_ha"),
    ("mod_fiscal", "modulos_fiscais"),
    ("des_condic", "condicao"),
    ("dat_criaca", "data_criacao"),
    ("dat_atuali", "data_atualizacao"),
    ("alertas", "alertas"),
]
LEGAL_NOTICE = (
    "Dados declaratórios obtidos nos serviços públicos do SICAR. Esta resposta não atesta "
    "regularidade ambiental nem substitui o Demonstrativo oficial."
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    sicar.pool.open()
    sicar.ensure_schema()
    with sicar.pool.connection() as conn:
        pronto = conn.execute("SELECT to_regclass('public.indice_grupo') AS tabela").fetchone()["tabela"]
        if not pronto:
            indice.criar_esquema(conn)
    yield
    sicar.pool.close()


app = FastAPI(
    title="CAR em Recorte",
    description=(
        "Radar da fila do CAR e API de leitura sobre os serviços públicos do SICAR. As rotas do "
        "Radar usam um índice local; as consultas sob demanda reaproveitam respostas guardadas."
    ),
    version="0.5.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


app.include_router(rotas_radar.router)


@app.exception_handler(UpstreamError)
def upstream_error(_: Request, exc: UpstreamError) -> JSONResponse:
    sicar.log.warning("SICAR indisponível: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "O SICAR não respondeu a tempo. Tente de novo ou refine a busca."},
    )


@app.exception_handler(InvalidFilter)
def invalid_filter(_: Request, exc: InvalidFilter) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class BatchRequest(BaseModel):
    codigos: list[str] = Field(min_length=1, max_length=BATCH_LIMIT)
    incluir_temas: bool = True


def normalize_code(value: str) -> str:
    return value.strip().upper()


def check_code(value: str) -> str:
    code = normalize_code(value)
    if not CAR_CODE.fullmatch(code) or not sicar.layers_for_code(code):
        raise HTTPException(status_code=400, detail="Confira o código CAR informado.")
    return code


def base_info(uf: str, ibge: int | None = None, origin: str | None = None) -> dict[str, Any]:
    mark = sicar.fingerprint(uf, ibge)
    latest = sicar.br_day(mark["ultima"]) if mark else None
    return {
        "fonte": SOURCE,
        "consultado_em": datetime.now(timezone.utc).isoformat(),
        "atualizado_ate": latest.isoformat() if latest else None,
        "origem": origin,
    }


def build_filters(
    uf: str,
    municipality: str | None,
    status: str | None,
    condition: str | None,
    updated_since: date | None,
    app_to_restore: bool,
    area_min: float | None,
    area_max: float | None,
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
) -> SearchFilters:
    state = sicar.check_uf(uf)
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Situação cadastral inválida.")
    if condition is not None and condition not in CONDITION_GROUPS:
        raise HTTPException(status_code=400, detail="Condição do cadastro inválida.")
    if area_min is not None and area_max is not None and area_min > area_max:
        raise HTTPException(status_code=400, detail="Área mínima maior que a área máxima.")
    bbox = None
    values = (west, south, east, north)
    if any(value is not None for value in values):
        if any(value is None for value in values):
            raise HTTPException(
                status_code=400, detail="Informe os quatro limites do retângulo desenhado no mapa."
            )
        assert west is not None and south is not None and east is not None and north is not None
        if west >= east or south >= north:
            raise HTTPException(status_code=400, detail="Retângulo geográfico inválido.")
        bbox = (west, south, east, north)
    city = sicar.find_municipality(state, municipality)
    return SearchFilters(
        uf=state,
        municipality=city["name"] if city else None,
        ibge=city["ibge"] if city else None,
        status=status,
        condition=condition,
        updated_since=updated_since.isoformat() if updated_since else None,
        app_to_restore=app_to_restore,
        area_min=area_min,
        area_max=area_max,
        bbox=bbox,
    )


def alert_items(codes: list[str]) -> list[dict[str, str]]:
    return [{"codigo": code, "descricao": ALERT_LABELS.get(code, code)} for code in sorted(set(codes))]


def summarize(properties: dict[str, Any], overlap_codes: list[str] | None = None) -> dict[str, Any]:
    alerts = [*properties.get("alertas", []), *(overlap_codes or [])]
    status = properties.get("ind_status")
    return {
        "codigo_car": properties["cod_imovel"],
        "encontrado": True,
        "situacao": status,
        "situacao_descricao": STATUS_LABELS.get(status, status),
        "condicao": properties.get("des_condic"),
        "condicao_grupo": properties.get("condicao_grupo"),
        "municipio": properties.get("municipio"),
        "uf": properties.get("cod_estado"),
        "tipo_imovel": properties.get("ind_tipo"),
        "area_declarada_ha": properties.get("num_area"),
        "modulos_fiscais": properties.get("mod_fiscal"),
        "data_inscricao": properties.get("data_criacao"),
        "data_atualizacao": properties.get("data_atualizacao"),
        "origem": "sicar",
        "alertas": alert_items(alerts),
    }


def load_property(code: str) -> dict[str, Any]:
    feature = sicar.get_property(code)
    if not feature:
        raise HTTPException(status_code=404, detail="Código não encontrado no SICAR.")
    return feature


def batch_lookup(payload: BatchRequest) -> dict[str, Any]:
    started = time.perf_counter()
    requested = [normalize_code(code) for code in payload.codigos]
    unique = list(dict.fromkeys(code for code in requested if code))
    valid = [code for code in unique if CAR_CODE.fullmatch(code) and sicar.layers_for_code(code)]

    properties = sicar.get_properties(valid)
    found_codes = list(properties)
    by_type: dict[str, list[str]] = {}
    for code, item in properties.items():
        by_type.setdefault(item.get("ind_tipo") or "", []).append(code)
    overlaps = sicar.overlaps(by_type)

    counts: dict[str, dict[str, Any]] = {}
    themes_available = True
    if payload.incluir_temas and found_codes:
        try:
            counts = sicar.theme_counts(found_codes)
        except UpstreamError:
            themes_available = False

    items: list[dict[str, Any]] = []
    for code in unique:
        if code in properties:
            item = summarize(properties[code], overlaps.get(code))
            if payload.incluir_temas and themes_available:
                theme = counts.get(code, {"camadas": {}, "recompor": 0})
                item["temas"] = {
                    key: {"feicoes": total, "area_ha": None}
                    for key, total in theme["camadas"].items()
                }
                item["app_a_recompor_feicoes"] = theme["recompor"]
        else:
            valid_code = CAR_CODE.fullmatch(code) and sicar.layers_for_code(code)
            item = {
                "codigo_car": code,
                "encontrado": False,
                "motivo": "nao_encontrado" if valid_code else "codigo_invalido",
            }
        items.append(item)

    found = sum(item["encontrado"] for item in items)
    return {
        "resumo": {
            "recebidos": len(requested),
            "unicos": len(unique),
            "encontrados": found,
            "nao_encontrados": len(unique) - found,
            "com_alerta": sum(bool(item.get("alertas")) for item in items),
        },
        "itens": items,
        "camadas": THEME_LABELS,
        "temas_disponiveis": themes_available,
        "base": {"fonte": SOURCE, "consultado_em": datetime.now(timezone.utc).isoformat()},
        "aviso": LEGAL_NOTICE,
        "metrics": {"api_ms": round((time.perf_counter() - started) * 1000, 2)},
    }


def csv_response(body: str, filename: str, records: int) -> Response:
    return Response(
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Records": str(records),
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    """Confere só o cache local, para o monitoramento não gerar chamadas ao SICAR."""
    try:
        with sicar.pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "cache": "connected"}
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Cache indisponível") from exc


@app.get("/api/estados")
def states() -> dict[str, Any]:
    return {"estados": sicar.states()}


@app.get("/api/meta")
def meta(uf: str = "MA") -> dict[str, Any]:
    """Cobertura, situação da fonte e opções aceitas pelos filtros."""
    state = sicar.check_uf(uf)
    mark = sicar.fingerprint(state)
    counts = sicar.condition_counts(state)
    return {
        "cobertura": sorted(sicar.UFS),
        "uf": state,
        "registros": mark["total"] if mark else None,
        "base": base_info(state),
        "limites": {"lote": BATCH_LIMIT, "exportacao": EXPORT_LIMIT},
        "condicoes": [
            {"id": key, "rotulo": label, "registros": counts.get(key)}
            for key, (label, _) in CONDITION_GROUPS.items()
        ],
        "aviso": LEGAL_NOTICE,
    }


@app.get("/api/summary")
def summary(uf: str = "MA") -> dict[str, Any]:
    state = sicar.check_uf(uf)
    mark = sicar.fingerprint(state)
    return {
        "status": "ready",
        "state": state,
        "property_count": mark["total"] if mark else None,
        "layers": [{"id": "area_imovel", "label": "Limite do imóvel", "kind": "property"}]
        + [{"id": key, "label": label, "kind": "theme"} for key, label in THEME_LABELS.items()],
    }


@app.get("/api/cache/metricas")
def cache_metrics(response: Response) -> dict[str, Any]:
    """Quanto o cache evitou de chamadas e de dados vindos do SICAR."""
    response.headers["Cache-Control"] = "no-store"
    return sicar.metrics()


@app.get("/api/municipalities")
def municipalities(uf: str = "MA") -> dict[str, Any]:
    """Municípios da UF, com os limites informados pela Consulta Pública."""
    state = sicar.check_uf(uf)
    mark = sicar.fingerprint(state)
    return {
        "state": state,
        "source": SOURCE,
        "property_count": mark["total"] if mark else None,
        "base": base_info(state),
        "municipalities": [
            {"name": item["name"], "ibge": item["ibge"], "property_count": None, "bounds": item["bounds"]}
            for item in sicar.municipalities(state)
        ],
    }


@app.get("/api/search")
def search_properties(
    uf: str = Query(default="MA", min_length=2, max_length=2),
    municipality: str | None = Query(default=None, max_length=100),
    status: str | None = None,
    condition: str | None = None,
    updated_since: date | None = None,
    app_to_restore: bool = False,
    area_min: float | None = Query(default=None, ge=0),
    area_max: float | None = Query(default=None, ge=0),
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Busca paginada direto nos serviços do SICAR, passando pelo cache."""
    started = time.perf_counter()
    filters = build_filters(
        uf, municipality or None, status, condition, updated_since, app_to_restore,
        area_min, area_max, west, south, east, north,
    )
    result, info = sicar.search(filters, page, page_size)
    total = result["total"]
    return {
        "uf": filters.uf,
        "municipality": filters.municipality,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "source": SOURCE,
        "base": base_info(filters.uf, filters.ibge, info["origem"]),
        "metrics": {
            "records_matched": total,
            "records_returned": len(result["features"]),
            "api_ms": round((time.perf_counter() - started) * 1000, 2),
            "origem": info["origem"],
            "chamadas_sicar": info["chamadas_sicar"],
        },
        "features": result["features"],
    }


@app.get("/api/search/export")
def export_search(
    format: str = Query(pattern="^(csv|geojson)$"),
    uf: str = Query(default="MA", min_length=2, max_length=2),
    municipality: str | None = Query(default=None, max_length=100),
    status: str | None = None,
    condition: str | None = None,
    updated_since: date | None = None,
    app_to_restore: bool = False,
    area_min: float | None = Query(default=None, ge=0),
    area_max: float | None = Query(default=None, ge=0),
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
) -> Response:
    """Exporta todos os registros filtrados, até 10.000, em CSV ou GeoJSON."""
    filters = build_filters(
        uf, municipality or None, status, condition, updated_since, app_to_restore,
        area_min, area_max, west, south, east, north,
    )
    first, _ = sicar.search(filters, 1, 1)
    total = first["total"]
    if total > EXPORT_LIMIT:
        raise HTTPException(
            status_code=413,
            detail="A consulta tem mais de 10.000 imóveis. Refine os filtros ou desenhe um retângulo menor.",
        )
    features, _ = sicar.export(filters, format == "geojson", total)
    stem = sicar.plain(filters.municipality or filters.uf)
    safe_name = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "recorte"
    prefix = f"car-{filters.uf.lower()}-{safe_name}"
    if format == "geojson":
        body = json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return Response(
            content=body,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f'attachment; filename="{prefix}.geojson"',
                "X-Export-Records": str(len(features)),
            },
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for feature in features:
        p = feature["properties"]
        writer.writerow(
            ["|".join(p.get(column) or []) if column == "alertas" else p.get(column) for column, _ in EXPORT_COLUMNS]
        )
    return csv_response(output.getvalue(), f"{prefix}.csv", len(features))


@app.post("/api/consultas/lote")
def batch_query(payload: BatchRequest) -> dict[str, Any]:
    """Consulta até 1.000 códigos CAR de qualquer UF, sem transferir geometrias."""
    return batch_lookup(payload)


@app.post("/api/consultas/lote.csv")
def batch_query_csv(payload: BatchRequest) -> Response:
    """Mesma consulta em lote, em CSV separado por ponto e vírgula."""
    result = batch_lookup(payload)
    theme_keys = list(THEME_LABELS) if payload.incluir_temas else []
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "codigo_car", "encontrado", "motivo", "situacao", "condicao", "municipio", "uf",
            "tipo_imovel", "area_declarada_ha", "modulos_fiscais", "data_inscricao",
            "data_atualizacao", "alertas", "app_a_recompor_feicoes",
            *[f"{key}_feicoes" for key in theme_keys],
        ]
    )
    for item in result["itens"]:
        themes = item.get("temas", {})
        writer.writerow(
            [
                item["codigo_car"], "sim" if item["encontrado"] else "nao", item.get("motivo", ""),
                item.get("situacao", ""), item.get("condicao", ""), item.get("municipio", ""),
                item.get("uf", ""), item.get("tipo_imovel", ""), item.get("area_declarada_ha", ""),
                item.get("modulos_fiscais", ""), item.get("data_inscricao", ""),
                item.get("data_atualizacao", ""),
                "|".join(alert["codigo"] for alert in item.get("alertas", [])),
                item.get("app_a_recompor_feicoes", ""),
                *[
                    themes.get(key, {}).get("feicoes", 0) if "temas" in item else ""
                    for key in theme_keys
                ],
            ]
        )
    return csv_response(output.getvalue(), "car-consulta-em-lote.csv", len(result["itens"]))


def property_payload(code: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    feature = load_property(code)
    properties = feature["properties"]
    themes = sicar.property_themes(code, feature.get("geometry"), properties.get("data_atualizacao"))
    kind = properties.get("ind_tipo") or ""
    overlap_codes = sicar.overlaps({kind: [code]}).get(code, [])
    item = summarize(properties, overlap_codes)
    declared, calculated = properties.get("num_area"), themes.get("area_calculada_ha")
    if declared and calculated and abs(declared - calculated) > max(1, declared * 0.2):
        item["alertas"] = alert_items([*(a["codigo"] for a in item["alertas"]), "area_divergente"])
    item["area_calculada_ha"] = calculated
    item["app_a_recompor_ha"] = themes.get("app_a_recompor_ha", 0)
    return feature, item, themes


@app.get("/api/imoveis/{car_code}")
def property_summary(car_code: str) -> dict[str, Any]:
    """Cadastro, limite do imóvel e resumo das camadas ambientais oficiais."""
    code = check_code(car_code)
    feature, item, themes = property_payload(code)
    return {
        **item,
        "limites": [feature],
        "temas": themes["linhas"],
        "camadas": THEME_LABELS,
        "base": {"fonte": SOURCE, "consultado_em": datetime.now(timezone.utc).isoformat()},
        "aviso": LEGAL_NOTICE,
    }


@app.get("/api/lookup/{car_code}")
def lookup(car_code: str) -> dict[str, Any]:
    """Resposta completa, com a geometria de todas as camadas do imóvel."""
    code = check_code(car_code)
    feature, _, themes = property_payload(code)
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in THEME_LABELS}
    for item in themes["features"]:
        grouped.setdefault(item["properties"].get("camada") or "ecossistemas_relevo", []).append(item)
    return {
        "codigo_car": code,
        "imoveis": [feature],
        "temas": grouped,
        "origem": {
            "imovel": "WFS público do SICAR",
            "temas": "WFS público da Consulta Pública do CAR",
        },
        "camadas": THEME_LABELS,
    }
