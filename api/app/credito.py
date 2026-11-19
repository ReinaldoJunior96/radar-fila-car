"""Verificação em lote para análise de crédito rural.

Resolve pelo índice local, sem chamar o SICAR. Códigos de estados ainda não indexados são
buscados ao vivo, com cache, e recebem só os pontos que dependem do cadastro.
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import date
from typing import Any

from . import classificacao, sicar

LIMITE = 1000
CODIGO = re.compile(r"^[A-Z]{2}-[0-9]{7}-[A-Z0-9.]{8,64}$")
AVISO = (
    "Os pontos de atenção organizam dados públicos para triagem. Não substituem as consultas exigidas "
    "pelas normas de crédito rural nem a análise do órgão ambiental competente."
)
# Perfil do índice -> (nível, texto do ponto de atenção)
PONTOS = {
    "status_cancelado": ("alta", "Cadastro cancelado"),
    "status_suspenso": ("alta", "Cadastro suspenso"),
    "sobre_embargo": ("alta", "Sobreposição com área embargada"),
    "sobre_indigena": ("alta", "Sobreposição com terra indígena"),
    "status_pendente": ("atencao", "Cadastro pendente"),
    "sobre_uc": ("atencao", "Sobreposição com unidade de conservação"),
    "sobre_quilombo": ("atencao", "Sobreposição com território quilombola"),
    "sobre_uniao": ("atencao", "Sobreposição com terras da União"),
    "app_recompor": ("atencao", "APP a recompor"),
    "aguardando_regularizacao": ("atencao", "Analisado, aguardando regularização ambiental"),
    "aguardando_atendimento": ("atencao", "Analisado, aguardando atendimento a notificação"),
    "area_atipica": ("atencao", "Área declarada atípica"),
    "sem_analise": ("info", "Sem análise concluída"),
    "fila_5_anos": ("info", "Na fila há 5 anos ou mais"),
    "acima_15_modulos": ("info", "Acima de 15 módulos fiscais"),
    "retificado_3x": ("info", "Três retificações ou mais"),
    "analisado_conforme": ("info", "Analisado em conformidade"),
}
ORDEM_NIVEL = {"alta": 0, "atencao": 1, "info": 2}


def normalizar(codigo: str) -> str:
    return re.sub(r"\s+", "", codigo or "").upper()


def pontos(perfis: list[str], indicadores_ambientais: bool = True) -> list[dict[str, str]]:
    itens = [
        {"codigo": perfil, "nivel": PONTOS[perfil][0], "texto": PONTOS[perfil][1],
         "fonte": classificacao.POR_CODIGO[perfil].fonte}
        for perfil in perfis if perfil in PONTOS
    ]
    if not indicadores_ambientais:
        itens.append({"codigo": "indicadores_nao_verificados", "nivel": "atencao",
                      "texto": "Indicadores ambientais não verificados: estado fora do índice", "fonte": "—"})
    return sorted(itens, key=lambda item: ORDEM_NIVEL[item["nivel"]])


def _resultado(item: dict[str, Any]) -> str:
    niveis = {ponto["nivel"] for ponto in item["pontos"]}
    if "alta" in niveis:
        return "atencao_alta"
    return "atencao" if "atencao" in niveis else "sem_pontos"


def verificar(codigos: list[str]) -> dict[str, Any]:
    inicio = time.perf_counter()
    hoje = date.today()
    recebidos = [normalizar(c) for c in codigos]
    unicos = list(dict.fromkeys(c for c in recebidos if c))
    validos = [c for c in unicos if CODIGO.fullmatch(c)]
    with sicar.pool.connection() as conn:
        linhas = {
            linha["cod_imovel"]: linha
            for linha in conn.execute("SELECT * FROM indice_imovel WHERE cod_imovel = ANY(%s)", (validos,))
        }
        marcas = {
            linha["uf"]: linha["marca"]
            for linha in conn.execute("SELECT uf, marca FROM sync_estado")
        }
    faltantes = [c for c in validos if c not in linhas]
    ao_vivo: dict[str, dict[str, Any]] = {}
    chamadas_antes = sicar.metrics()["chamadas_ao_sicar"] if faltantes else 0
    if faltantes:
        ao_vivo = sicar.get_properties(faltantes)
    chamadas = sicar.metrics()["chamadas_ao_sicar"] - chamadas_antes if faltantes else 0
    itens = []
    for codigo in unicos:
        if codigo in linhas:
            linha = linhas[codigo]
            item = {
                "codigo_car": codigo, "encontrado": True, "origem": "indice", "uf": linha["uf"],
                "municipio": linha["municipio"], "situacao": linha["status"], "condicao": linha["condicao"],
                "area_ha": linha["area_ha"], "modulos_fiscais": linha["modulos"],
                "dados_ate": marcas.get(linha["uf"]).isoformat() if marcas.get(linha["uf"]) else None,
                "pontos": pontos(linha["perfis"]),
            }
        elif codigo in ao_vivo:
            fonte = ao_vivo[codigo]
            linha = {
                "status": fonte.get("ind_status"), "condicao_grupo": fonte.get("condicao_grupo"),
                "condicao": fonte.get("des_condic"), "data_criacao": fonte.get("data_criacao"),
                "area_ha": fonte.get("num_area"), "modulos": fonte.get("mod_fiscal"), "sobreposicoes": [],
            }
            perfis, _ = classificacao.classificar(linha, hoje)
            item = {
                "codigo_car": codigo, "encontrado": True, "origem": "sicar_ao_vivo", "uf": fonte.get("cod_estado"),
                "municipio": fonte.get("municipio"), "situacao": linha["status"], "condicao": linha["condicao"],
                "area_ha": linha["area_ha"], "modulos_fiscais": linha["modulos"], "dados_ate": hoje.isoformat(),
                "pontos": pontos(perfis, indicadores_ambientais=False),
            }
        else:
            item = {
                "codigo_car": codigo, "encontrado": False, "origem": None,
                "motivo": "codigo_invalido" if codigo not in validos else "nao_encontrado",
                "pontos": [{"codigo": "nao_encontrado", "nivel": "alta",
                            "texto": "Código inválido" if codigo not in validos else "Código não encontrado no SICAR",
                            "fonte": "WFS do SICAR"}],
            }
        item["resultado"] = _resultado(item)
        itens.append(item)
    return {
        "resumo": {
            "recebidos": len(recebidos),
            "unicos": len(unicos),
            "no_indice": sum(i["origem"] == "indice" for i in itens),
            "ao_vivo": sum(i["origem"] == "sicar_ao_vivo" for i in itens),
            "nao_encontrados": sum(not i["encontrado"] for i in itens),
            "atencao_alta": sum(i["resultado"] == "atencao_alta" for i in itens),
            "atencao": sum(i["resultado"] == "atencao" for i in itens),
            "sem_pontos": sum(i["resultado"] == "sem_pontos" for i in itens),
        },
        "itens": itens,
        "chamadas_sicar": chamadas,
        "tempo_ms": round((time.perf_counter() - inicio) * 1000, 1),
        "aviso": AVISO,
    }


def csv_verificacao(resultado: dict[str, Any]) -> tuple[str, int]:
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow([
        "codigo_car", "resultado", "origem", "uf", "municipio", "situacao", "condicao", "area_ha",
        "modulos_fiscais", "atencao_alta", "atencao", "informativos", "dados_ate",
    ])
    for item in resultado["itens"]:
        por_nivel = {nivel: "; ".join(p["texto"] for p in item["pontos"] if p["nivel"] == nivel) for nivel in ORDEM_NIVEL}
        escritor.writerow([
            item["codigo_car"], item["resultado"], item.get("origem") or "", item.get("uf") or "",
            item.get("municipio") or "", item.get("situacao") or "", item.get("condicao") or "",
            item.get("area_ha") or "", item.get("modulos_fiscais") or "", por_nivel["alta"],
            por_nivel["atencao"], por_nivel["info"], item.get("dados_ate") or "",
        ])
    return saida.getvalue(), len(resultado["itens"])
