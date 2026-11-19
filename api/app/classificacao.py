"""Perfis explicáveis da fila do CAR.

Os perfis organizam dados públicos para consulta. A prioridade é uma sugestão de triagem,
com pesos revisáveis, e não indica regularidade ou irregularidade ambiental.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

VERSAO = "v1"
Linha = dict[str, Any]


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def idade_anos(linha: Linha, hoje: date) -> float | None:
    created = linha.get("data_criacao")
    if not created:
        return None
    if isinstance(created, str):
        created = date.fromisoformat(created[:10])
    return max((hoje - created).days / 365.25, 0.0)


def _sem_analise(linha: Linha) -> bool:
    return linha.get("condicao_grupo") == "aguardando_analise" and linha.get("status") != "CA"


def _fila_minima(anos: float) -> Callable[[Linha, date], bool]:
    def regra(linha: Linha, hoje: date) -> bool:
        idade = idade_anos(linha, hoje)
        return _sem_analise(linha) and idade is not None and idade >= anos

    return regra


def _sobreposicao(campo: str) -> Callable[[Linha, date], bool]:
    return lambda linha, _: campo in (linha.get("sobreposicoes") or [])


@dataclass(frozen=True)
class Perfil:
    codigo: str
    rotulo: str
    descricao: str
    fonte: str
    peso: int
    regra: Callable[[Linha, date], bool]
    grupo: str


PERFIS = [
    Perfil("sem_analise", "Sem análise concluída", "Condição informada como aguardando análise.", "condicao, WFS do SICAR", 10, lambda l, _: _sem_analise(l), "Fila"),
    Perfil("fila_5_anos", "Na fila há 5 anos ou mais", "Aguardando análise e criado há pelo menos 5 anos.", "condicao e dat_criacao, WFS do SICAR", 15, _fila_minima(5), "Fila"),
    Perfil("fila_10_anos", "Na fila há 10 anos ou mais", "Aguardando análise e criado há pelo menos 10 anos.", "condicao e dat_criacao, WFS do SICAR", 10, _fila_minima(10), "Fila"),
    Perfil("retorno_revisao", "Retorno após revisão", "Aguardando análise após revisão ou atendimento de notificação.", "condicao, WFS do SICAR", 10, lambda l, _: "apos revisao" in _plain(l.get("condicao")), "Fila"),
    Perfil("em_analise", "Em análise", "Condição informada como em análise.", "condicao, WFS do SICAR", 0, lambda l, _: l.get("condicao_grupo") == "em_analise", "Etapa"),
    Perfil("aguardando_atendimento", "Aguardando atendimento", "Analisado, aguardando atendimento a notificação.", "condicao, WFS do SICAR", 10, lambda l, _: l.get("condicao_grupo") == "analisado_notificacao", "Etapa"),
    Perfil("aguardando_regularizacao", "Aguardando regularização", "Analisado, aguardando regularização ambiental.", "condicao, WFS do SICAR", 15, lambda l, _: l.get("condicao_grupo") == "analisado_regularizacao", "Etapa"),
    Perfil("analisado_conforme", "Analisado em conformidade", "Condição informada como em conformidade com a Lei nº 12.651/2012.", "condicao, WFS do SICAR", 0, lambda l, _: l.get("condicao_grupo") == "analisado_conforme", "Etapa"),
    Perfil("app_recompor", "APP a recompor", "Possui feição em camada oficial de APP a recompor.", "camadas app_escadinha, Consulta Pública", 10, lambda l, _: bool(l.get("tem_app_recompor")), "Ambiental"),
    Perfil("sobre_embargo", "Sobreposição com área embargada", "Indicador oficial de sobreposição maior que zero.", "sobreposicao_area_embargada, Consulta Pública", 20, _sobreposicao("sobreposicao_area_embargada"), "Sobreposição"),
    Perfil("sobre_indigena", "Sobreposição com terra indígena", "Indicador oficial de sobreposição maior que zero.", "sobreposicao_area_indigena, Consulta Pública", 20, _sobreposicao("sobreposicao_area_indigena"), "Sobreposição"),
    Perfil("sobre_uc", "Sobreposição com unidade de conservação", "Indicador oficial de sobreposição maior que zero.", "sobreposicao_unidade_conservacao, Consulta Pública", 15, _sobreposicao("sobreposicao_unidade_conservacao"), "Sobreposição"),
    Perfil("sobre_quilombo", "Sobreposição com território quilombola", "Indicador oficial de sobreposição maior que zero.", "sobreposicao_quilombo, Consulta Pública", 15, _sobreposicao("sobreposicao_quilombo"), "Sobreposição"),
    Perfil("sobre_uniao", "Sobreposição com terras da União", "Indicador oficial de sobreposição maior que zero.", "sobreposicao_terras_da_uniao, Consulta Pública", 10, _sobreposicao("sobreposicao_terras_da_uniao"), "Sobreposição"),
    Perfil("status_pendente", "Cadastro pendente", "Situação cadastral pendente.", "status_imovel, WFS do SICAR", 5, lambda l, _: l.get("status") == "PE", "Situação"),
    Perfil("status_suspenso", "Cadastro suspenso", "Situação cadastral suspensa.", "status_imovel, WFS do SICAR", 5, lambda l, _: l.get("status") == "SU", "Situação"),
    Perfil("status_cancelado", "Cadastro cancelado", "Situação cadastral cancelada.", "status_imovel, WFS do SICAR", 0, lambda l, _: l.get("status") == "CA", "Situação"),
    Perfil("acima_15_modulos", "Acima de 15 módulos fiscais", "Área declarada acima de 15 módulos fiscais.", "m_fiscal, WFS do SICAR", 10, lambda l, _: (l.get("modulos") or 0) > 15, "Porte"),
    Perfil("retificado_3x", "Três retificações ou mais", "A camada de área consolidada registra pelo menos 3 retificações.", "nu_retificacao, Consulta Pública", 5, lambda l, _: (l.get("retificacoes") or 0) >= 3, "Histórico"),
    Perfil("area_atipica", "Área declarada atípica", "Área declarada acima de 100 mil hectares ou sem valor positivo.", "area, WFS do SICAR", 5, lambda l, _: not l.get("area_ha") or l["area_ha"] > 100000, "Qualidade"),
]
POR_CODIGO = {perfil.codigo: perfil for perfil in PERFIS}


def classificar(linha: Linha, hoje: date) -> tuple[list[str], int]:
    """Devolve os perfis e a prioridade sugerida, de 0 a 100."""
    codigos = [perfil.codigo for perfil in PERFIS if perfil.regra(linha, hoje)]
    if linha.get("status") == "CA":
        return codigos, 0
    return codigos, min(100, sum(POR_CODIGO[codigo].peso for codigo in codigos))


def motivos(codigos: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "codigo": codigo,
            "rotulo": POR_CODIGO[codigo].rotulo,
            "motivo": POR_CODIGO[codigo].descricao,
            "fonte": POR_CODIGO[codigo].fonte,
            "peso": POR_CODIGO[codigo].peso,
        }
        for codigo in codigos
        if codigo in POR_CODIGO
    ]


def catalogo() -> list[dict[str, Any]]:
    return [
        {
            "codigo": perfil.codigo,
            "rotulo": perfil.rotulo,
            "descricao": perfil.descricao,
            "fonte": perfil.fonte,
            "peso": perfil.peso,
            "grupo": perfil.grupo,
            "versao": VERSAO,
        }
        for perfil in PERFIS
    ]
