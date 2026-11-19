"""Rotas do Radar, do assistente e da central de conhecimento."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import assistente, credito, radar
from .sicar import InvalidFilter

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
    analisado_desde: date | None = Query(None, description="Condição mudou para analisado a partir desta data"),
    alterado_desde: date | None = Query(None, description="Condição ou situação mudou a partir desta data"),
    atualizado_desde: date | None = Query(None, description="Data de atualização no SICAR a partir desta data"),
    oeste: float | None = None,
    sul: float | None = None,
    leste: float | None = None,
    norte: float | None = None,
    ordem: str = "prioridade",
) -> radar.FiltroFila:
    caixa = (oeste, sul, leste, norte)
    if any(v is not None for v in caixa) and not all(v is not None for v in caixa):
        raise InvalidFilter("Informe oeste, sul, leste e norte juntos.")
    return radar.FiltroFila(
        uf=uf, ibge=ibge, perfis=[item for item in (perfis or "").split(",") if item],
        condicao=condicao or None, status=status or None, tipo=tipo or None,
        prioridade_min=prioridade_min, anos_min=anos_min, area_min=area_min, area_max=area_max,
        grupo=grupo, com_sobreposicao=com_sobreposicao, analisado_desde=analisado_desde,
        alterado_desde=alterado_desde, atualizado_desde=atualizado_desde,
        bbox=caixa if all(v is not None for v in caixa) else None, ordem=ordem,
    )


@router.get("/radar/estados", summary="Nomes das unidades federativas")
def estados() -> dict[str, Any]:
    return {"estados": radar.ESTADOS}


@router.get("/radar/resumo", summary="Indicadores da fila por UF ou município")
def resumo(uf: str = "MA", ibge: int | None = Query(None, ge=1)) -> dict[str, Any]:
    return radar.resumo(uf, ibge)


@router.get("/radar/recorte", summary="Indicadores do recorte filtrado (mesmos filtros da fila)")
def recorte(
    filtro: radar.FiltroFila = Depends(filtro_fila),
    municipios: int = Query(10, ge=1, le=300, description="Quantos municípios devolver no ranking"),
) -> dict[str, Any]:
    return radar.recorte(filtro, municipios)


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


@router.get("/radar/movimentos", summary="Linha do tempo das etapas e das mudanças detectadas")
def movimentos(uf: str = "MA", ibge: int | None = Query(None, ge=1), dias: int = Query(90, ge=1, le=730)) -> dict[str, Any]:
    return radar.movimentos(uf, ibge, dias)


@router.get("/radar/imovel/{codigo}", summary="Dados do índice e histórico de um imóvel")
def imovel(codigo: str) -> dict[str, Any]:
    dados = radar.imovel(codigo.strip().upper())
    if not dados:
        raise HTTPException(status_code=404, detail="Imóvel fora do índice.")
    return dados


@router.get("/radar/mapa", summary="Limites dos imóveis do recorte, em GeoJSON, do índice espacial")
def mapa(filtro: radar.FiltroFila = Depends(filtro_fila)) -> dict[str, Any]:
    return radar.mapa(filtro)


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
def perguntar(
    q: str = Query(..., min_length=2, max_length=300),
    uf: str = "MA",
    contexto: str | None = Query(None, max_length=2000, description="Filtros da resposta anterior, em JSON"),
) -> dict[str, Any]:
    anterior = None
    if contexto:
        try:
            anterior = json.loads(contexto)
        except ValueError as exc:
            raise InvalidFilter("Contexto inválido.") from exc
    return assistente.responder(q, uf, anterior if isinstance(anterior, dict) else None)


class PedidoCredito(BaseModel):
    codigos: list[str] = Field(..., min_length=1, max_length=credito.LIMITE)


@router.post("/credito/verificacao", summary="Pontos de atenção de até 1.000 imóveis", tags=["Crédito"])
def verificar(pedido: PedidoCredito) -> dict[str, Any]:
    return credito.verificar(pedido.codigos)


@router.post("/credito/verificacao.csv", summary="Mesma verificação em CSV", tags=["Crédito"])
def verificar_csv(pedido: PedidoCredito) -> Response:
    corpo, total = credito.csv_verificacao(credito.verificar(pedido.codigos))
    return Response(
        "\ufeff" + corpo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="verificacao_credito_car.csv"', "X-Registros": str(total)},
    )


@router.get("/conhecimento", summary="Guias, glossário, metodologia e links oficiais", tags=["Conhecimento"])
def conhecimento() -> dict[str, Any]:
    return json.loads(CONHECIMENTO.read_text(encoding="utf-8"))
