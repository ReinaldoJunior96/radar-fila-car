"""Rotas do Radar, do assistente e da central de conhecimento."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from . import assistente, radar

router = APIRouter(prefix="/api", tags=["Radar"])
CONHECIMENTO = Path(__file__).with_name("conhecimento.json")


def filtro_fila(
    uf: str = "MA",
    ibge: int | None = Query(None, ge=1),
    perfis: str | None = Query(None, description="Códigos separados por vírgula; o imóvel precisa ter todos."),
    condicao: str | None = None,
    status: str | None = None,
    tipo: str | None = None,
    prioridade_min: int | None = Query(None, ge=0, le=100),
    anos_min: float | None = Query(None, ge=0, le=100),
    area_min: float | None = Query(None, ge=0),
    area_max: float | None = Query(None, ge=0),
    grupo: int | None = Query(None, ge=0),
    com_sobreposicao: bool = False,
    ordem: str = "prioridade",
) -> radar.FiltroFila:
    return radar.FiltroFila(
        uf=uf, ibge=ibge, perfis=[item for item in (perfis or "").split(",") if item],
        condicao=condicao or None, status=status or None, tipo=tipo or None,
        prioridade_min=prioridade_min, anos_min=anos_min, area_min=area_min, area_max=area_max,
        grupo=grupo, com_sobreposicao=com_sobreposicao, ordem=ordem,
    )


@router.get("/radar/estados", summary="Nomes das unidades federativas")
def estados() -> dict[str, Any]:
    return {"estados": radar.ESTADOS}


@router.get("/radar/resumo", summary="Indicadores da fila por UF ou município")
def resumo(uf: str = "MA", ibge: int | None = Query(None, ge=1)) -> dict[str, Any]:
    return radar.resumo(uf, ibge)


@router.get("/radar/fila", summary="Imóveis filtrados por perfil, com os motivos")
def fila(
    filtro: radar.FiltroFila = Depends(filtro_fila),
    pagina: int = Query(1, ge=1, le=100000),
    por_pagina: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    return radar.fila(filtro, pagina, por_pagina)


@router.get("/radar/fila/export", summary="CSV da fila filtrada")
def exportar(filtro: radar.FiltroFila = Depends(filtro_fila)) -> Response:
    corpo, total = radar.exportar(filtro)
    return Response(
        "﻿" + corpo,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="radar_car_{filtro.uf.lower()}.csv"',
            "X-Registros": str(total),
        },
    )


@router.get("/radar/municipios", summary="Indicadores de todos os municípios indexados")
def municipios(uf: str = "MA") -> dict[str, Any]:
    return {"uf": uf.upper(), "municipios": radar.municipios(uf)}


@router.get("/radar/evolucao", summary="Fotografias diárias desde a primeira sincronização")
def evolucao(uf: str = "MA", ibge: int | None = Query(None, ge=1)) -> dict[str, Any]:
    return radar.evolucao(uf, ibge)


@router.get("/radar/grupos", summary="Padrões exploratórios encontrados por K-Means")
def grupos(uf: str = "MA") -> dict[str, Any]:
    return radar.grupos(uf)


@router.get("/perfis", summary="Regras, pesos e fontes dos perfis")
def perfis(uf: str | None = None, ibge: int | None = Query(None, ge=1)) -> dict[str, Any]:
    return radar.perfis(uf, ibge)


@router.get("/sincronizacao/status", summary="Situação e custo da sincronização")
def status(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return radar.status_sincronizacao()


@router.get("/assistente", summary="Responde perguntas em português usando o índice", tags=["Assistente"])
def perguntar(q: str = Query(..., min_length=2, max_length=300), uf: str = "MA") -> dict[str, Any]:
    return assistente.responder(q, uf)


@router.get("/conhecimento", summary="Guias, glossário, metodologia e links oficiais", tags=["Conhecimento"])
def conhecimento() -> dict[str, Any]:
    return json.loads(CONHECIMENTO.read_text(encoding="utf-8"))
