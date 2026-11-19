"""Assistente em português, por regras. Só executa consultas permitidas no índice."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import classificacao, radar, sicar
from .classificacao import _plain

EXEMPLOS = [
    "Quantos imóveis estão sem análise há mais de 5 anos?",
    "Quais municípios têm mais imóveis com APP a recompor?",
    "Mostre os 10 imóveis mais antigos na fila em Itapecuru Mirim",
    "Imóveis com sobreposição em território quilombola",
    "Cadastros aguardando regularização acima de 100 hectares",
]
ESTADOS = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG", "para": "PA",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}
PERFIS_TEXTO = [
    (r"sem analise|nao analisad|aguardando analise|na fila|parad[oa]s?|esperando analise", "sem_analise"),
    (r"app a recompor|recompor|recomposicao", "app_recompor"),
    (r"embargo|embargad", "sobre_embargo"),
    (r"indigena", "sobre_indigena"),
    (r"unidades? de conservacao", "sobre_uc"),
    (r"quilomb", "sobre_quilombo"),
    (r"terras? da uniao", "sobre_uniao"),
    (r"retorn\w* (apos|depois)|apos revisao", "retorno_revisao"),
    (r"(acima|mais) de 15 modulos", "acima_15_modulos"),
    (r"retificad|retificacoes", "retificado_3x"),
    (r"atipic", "area_atipica"),
]
CONDICOES_TEXTO = [
    (r"\bem analise\b", "em_analise"),
    (r"aguardando regularizacao", "analisado_regularizacao"),
    (r"aguardando atendimento|notificac", "analisado_notificacao"),
    (r"em conformidade|conformes?\b", "analisado_conforme"),
]
SITUACOES_TEXTO = [(r"cancelad", "CA"), (r"pendente", "PE"), (r"suspens", "SU"), (r"\bativos?\b", "AT")]
TIPOS_TEXTO = [(r"assentamento", "AST"), (r"comunidades? tradicion|povos", "PCT")]
NUMERO = r"(\d+(?:[.,]\d+)?)"


@dataclass
class Interpretacao:
    uf: str
    intencao: str = "lista"
    ibge: int | None = None
    municipio: str | None = None
    uf_pedida: str | None = None
    limite: int = 10
    filtro: dict[str, Any] = field(default_factory=dict)
    entendido: list[dict[str, str]] = field(default_factory=list)

    def anotar(self, campo: str, valor: str) -> None:
        self.entendido.append({"campo": campo, "valor": valor})


def _numero(texto: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):
        return float(texto.replace(".", ""))
    return float(texto.replace(".", "").replace(",", ".")) if "," in texto else float(texto)


def _hectares(valor: str, mil: str | None) -> float:
    return _numero(valor) * (1000 if mil else 1)


def interpretar(pergunta: str, uf: str, municipios: list[dict[str, Any]]) -> Interpretacao:
    texto = " ".join(_plain(pergunta).split())
    item = Interpretacao(uf=uf)
    filtro = item.filtro
    for nome, sigla in sorted(ESTADOS.items(), key=lambda par: -len(par[0])):
        if re.search(rf"\b(?:no|na|em|do|da|de) {nome}\b", texto):
            item.uf_pedida = sigla
            break
    for municipio in sorted(municipios, key=lambda m: -len(m["municipio"])):
        if re.search(rf"\b{re.escape(_plain(municipio['municipio']))}\b", texto):
            item.ibge, item.municipio = municipio["ibge"], municipio["municipio"]
            item.anotar("Município", municipio["municipio"])
            break
    if re.search(r"(qual|quais|ranking|lista de)\s+(?:d?os\s+)?municipios?|municipios? com mais|municipios? (?:tem|que tem)", texto):
        item.intencao = "ranking"
    elif re.search(r"\bquant[oa]s\b|\btotal de\b|\bnumero de\b", texto):
        item.intencao = "contagem"
    perfis: list[str] = []
    for padrao, codigo in PERFIS_TEXTO:
        if re.search(padrao, texto):
            perfis.append(codigo)
            item.anotar("Perfil", classificacao.POR_CODIGO[codigo].rotulo)
    if perfis:
        filtro["perfis"] = perfis
    if "sobreposic" in texto and not any(codigo.startswith("sobre_") for codigo in perfis):
        filtro["com_sobreposicao"] = True
        item.anotar("Indicador", "Qualquer sobreposição informada")
    if "sem_analise" not in perfis:
        for padrao, codigo in CONDICOES_TEXTO:
            if re.search(padrao, texto):
                filtro["condicao"] = codigo
                item.anotar("Condição", radar.CONDICOES[codigo])
                break
    for padrao, codigo in SITUACOES_TEXTO:
        if re.search(padrao, texto):
            filtro["status"] = codigo
            item.anotar("Situação", radar.SITUACOES[codigo])
            break
    for padrao, codigo in TIPOS_TEXTO:
        if re.search(padrao, texto):
            filtro["tipo"] = codigo
            item.anotar("Tipo", radar.TIPOS[codigo])
            break
    anos = re.search(rf"(?:ha|mais de|acima de|pelo menos|no minimo)\s+{NUMERO}\s+anos?", texto)
    if anos:
        filtro["anos_min"] = _numero(anos.group(1))
        item.anotar("Tempo desde a criação", f"{anos.group(1)} anos ou mais")
    minimo = re.search(rf"(?:mais de|acima de|maior(?:es)? (?:que|de)|pelo menos)\s+{NUMERO}\s*(mil)?\s*(?:ha\b|hectares?)", texto)
    if minimo:
        filtro["area_min"] = _hectares(minimo.group(1), minimo.group(2))
        item.anotar("Área mínima", f"{filtro['area_min']:g} ha")
    maximo = re.search(rf"(?:menos de|abaixo de|ate|menor(?:es)? (?:que|de))\s+{NUMERO}\s*(mil)?\s*(?:ha\b|hectares?)", texto)
    if maximo:
        filtro["area_max"] = _hectares(maximo.group(1), maximo.group(2))
        item.anotar("Área máxima", f"{filtro['area_max']:g} ha")
    prioridade = re.search(rf"prioridade\s+(?:acima de|maior que|minima de|de pelo menos)?\s*{NUMERO}", texto)
    if prioridade:
        filtro["prioridade_min"] = int(_numero(prioridade.group(1)))
        item.anotar("Prioridade mínima", prioridade.group(1))
    if "mais antig" in texto:
        filtro["ordem"] = "antiguidade"
        item.anotar("Ordem", "Mais antigos primeiro")
    elif re.search(r"\bmaiores\b|maior area", texto):
        filtro["ordem"] = "area"
        item.anotar("Ordem", "Maiores áreas primeiro")
    limite = re.search(r"\btop\s+(\d+)\b|\b(?:mostre|liste|ver)?\s*(?:os|as)\s+(\d+)\b", texto)
    if limite:
        item.limite = max(1, min(50, int(limite.group(1) or limite.group(2))))
    return item


def responder(pergunta: str, uf: str) -> dict[str, Any]:
    pergunta = pergunta.strip()
    uf = sicar.check_uf(uf)
    municipios = radar.municipios(uf)
    base = {"pergunta": pergunta, "uf": uf, "exemplos": EXEMPLOS, "chamadas_sicar": 0, "aviso": radar.AVISO}
    if not municipios:
        return {**base, "entendeu": False, "resposta": f"O índice de {uf} ainda não foi carregado."}
    item = interpretar(pergunta, uf, municipios)
    if item.uf_pedida and item.uf_pedida != uf:
        return {
            **base,
            "entendeu": False,
            "resposta": f"Esta consulta usa o índice de {uf}. O estado {item.uf_pedida} ainda não está disponível aqui.",
        }
    if not item.entendido:
        return {
            **base,
            "entendeu": False,
            "resposta": "Não identifiquei um filtro nessa pergunta. Tente citar um município, um perfil, uma condição ou um tempo de espera.",
        }
    filtro = radar.FiltroFila(uf=uf, ibge=item.ibge, **item.filtro).validar()
    parametros = {k: v for k, v in item.filtro.items()}
    if item.ibge:
        parametros["ibge"] = item.ibge
    saida = {**base, "entendeu": True, "entendido": item.entendido, "filtros": parametros, "intencao": item.intencao}
    if item.intencao == "ranking":
        filtro.ibge = item.ibge
        linhas = radar.ranking(filtro, item.limite)
        if linhas:
            primeiro = linhas[0]
            quantidade = f"{primeiro['total']:,}".replace(",", ".")
            texto = f"{primeiro['municipio']} lidera, com {quantidade} imóveis nesse recorte."
        else:
            texto = "Nenhum município tem imóveis nesse recorte."
        return {**saida, "resposta": texto, "ranking": linhas}
    resultado = radar.fila(filtro, 1, item.limite)
    total = f"{resultado['total']:,}".replace(",", ".")
    local = f" em {item.municipio}" if item.municipio else f" em {uf}"
    texto = f"{total} imóveis{local} atendem a esses filtros."
    if item.intencao == "contagem":
        return {**saida, "resposta": texto, "total": resultado["total"], "itens": []}
    return {**saida, "resposta": texto, "total": resultado["total"], "itens": resultado["itens"]}
