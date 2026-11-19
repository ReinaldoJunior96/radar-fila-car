"""Assistente em português, por regras. Só executa consultas permitidas no índice."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
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
    (r"grilagem|cobre[mn]? outros|engol|sobre outros (cars?|cadastros|imoveis)", "car_cobre_outros"),
    (r"duplicad|mesma area|dois cadastros|cadastros? repetid", "car_duplicado"),
    (r"dentro de outro|(sobreposic\w*|sobrepost\w*) (com|a|entre) (outros? )?(cars?|cadastros)\b", "car_dentro_de_outro"),
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
    if "sobreposic" in texto and not any(codigo.startswith(("sobre_", "car_")) for codigo in perfis):
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
    movimento = re.search(
        r"(analisad\w*|mud\w* de (?:etapa|condicao|situacao)|atualizad\w*)\s+(?:no|nos|na|nas)\s+"
        r"ultim[oa]s?\s+(?:(\d+)\s+)?(mes|meses|semanas?|dias?)", texto)
    if movimento:
        quantidade = int(movimento.group(2) or 1)
        unidade = movimento.group(3)
        dias = quantidade * (30 if unidade.startswith("mes") else 7 if unidade.startswith("semana") else 1)
        desde = date.today() - timedelta(days=dias)
        tipo = movimento.group(1)
        campo, rotulo = (
            ("analisado_desde", "Concluíram análise") if tipo.startswith("analisad")
            else ("alterado_desde", "Mudaram de etapa") if tipo.startswith("mud")
            else ("atualizado_desde", "Atualizados no SICAR")
        )
        filtro[campo] = desde.isoformat()
        item.anotar(rotulo, f"desde {desde:%d/%m/%Y}")
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


CONTINUACAO = re.compile(r"^(e|so|somente|apenas|agora|desses|destes|deles|delas|dentre eles|entre eles|filtre|mas)\b")
DEFINICAO = re.compile(
    r"^(o que (e|sao|significa|significam|quer dizer)|que (e|sao)|qual (e )?o significado|significado de|defina|definicao de|explique|explica)\b"
)
AJUDA = re.compile(r"^(ajuda|socorro|como (funciona|usar|uso|voce funciona)|o que (voce|vc) (faz|sabe|responde))\b")
CONHECIMENTO = Path(__file__).with_name("conhecimento.json")


def _palavras(texto: str) -> set[str]:
    return {palavra.rstrip("s") for palavra in re.findall(r"[a-z0-9_]+", _plain(texto)) if len(palavra) > 1}


def _base_conhecimento() -> list[tuple[str, str, str]]:
    dados = json.loads(CONHECIMENTO.read_text(encoding="utf-8"))
    itens = [(g["termo"], g["definicao"], "Glossário") for g in dados["glossario"]]
    itens += [(f"{c['campo']} {c['servico']}", c["descricao"], "Dicionário de dados") for c in dados["dicionario"]]
    itens += [(p.rotulo, f"{p.descricao} Fonte: {p.fonte}. Peso {p.peso}.", "Perfis do Radar") for p in classificacao.PERFIS]
    itens += [(f["pergunta"], f["resposta"], "Perguntas frequentes") for f in dados["faq"]]
    return itens


def definir(pergunta: str) -> dict[str, str] | None:
    """Encontra o termo do glossário, do dicionário ou dos perfis mais parecido com a pergunta."""
    alvo = _palavras(DEFINICAO.sub("", _plain(pergunta)))
    melhor: tuple[float, tuple[str, str, str] | None] = (0.0, None)
    for termo, texto, fonte in _base_conhecimento():
        termo_palavras = _palavras(termo)
        if not termo_palavras or not alvo:
            continue
        nota = len(alvo & termo_palavras) / len(termo_palavras | alvo)
        if nota > melhor[0]:
            melhor = (nota, (termo, texto, fonte))
    if melhor[0] < 0.25 or not melhor[1]:
        return None
    termo, texto, fonte = melhor[1]
    return {"termo": termo, "texto": texto, "fonte": fonte}


def _mesclar(item: Interpretacao, contexto: dict[str, Any], municipios: list[dict[str, Any]]) -> None:
    anteriores = dict(contexto.get("filtros") or {})
    perfis = list(dict.fromkeys([*(anteriores.get("perfis") or []), *(item.filtro.get("perfis") or [])]))
    item.filtro = {**anteriores, **item.filtro}
    if perfis:
        item.filtro["perfis"] = perfis
    if not item.ibge and contexto.get("ibge"):
        item.ibge = int(contexto["ibge"])
        item.municipio = next((m["municipio"] for m in municipios if m["ibge"] == item.ibge), None)
    item.entendido.insert(0, {"campo": "Continuação", "valor": "Filtros da pergunta anterior mantidos"})


def responder(pergunta: str, uf: str, contexto: dict[str, Any] | None = None) -> dict[str, Any]:
    pergunta = pergunta.strip()
    uf = sicar.check_uf(uf)
    base = {"pergunta": pergunta, "uf": uf, "exemplos": EXEMPLOS, "chamadas_sicar": 0, "aviso": radar.AVISO}
    texto = " ".join(_plain(pergunta).split())
    if AJUDA.search(texto):
        return {
            **base, "entendeu": True, "intencao": "ajuda", "contexto": contexto,
            "resposta": "Respondo perguntas sobre a fila do CAR usando o índice local: contagens, listas e rankings "
                        "por município, perfil, condição, situação, tempo, área e mudanças recentes. Também explico "
                        "termos do CAR. Você pode refinar a pergunta anterior começando com “e”, “só” ou “agora”.",
        }
    if DEFINICAO.search(texto):
        achado = definir(pergunta)
        if achado:
            return {
                **base, "entendeu": True, "intencao": "conhecimento", "contexto": contexto,
                "entendido": [{"campo": "Termo", "valor": achado["termo"]}],
                "resposta": achado["texto"], "fonte": achado["fonte"],
            }
    municipios = radar.municipios(uf)
    if not municipios:
        return {**base, "entendeu": False, "resposta": f"O índice de {uf} ainda não foi carregado."}
    item = interpretar(pergunta, uf, municipios)
    if item.uf_pedida and item.uf_pedida != uf:
        return {
            **base,
            "entendeu": False,
            "resposta": f"Esta consulta usa o índice de {uf}. O estado {item.uf_pedida} ainda não está disponível aqui.",
        }
    if contexto and item.entendido and CONTINUACAO.search(texto):
        _mesclar(item, contexto, municipios)
    if not item.entendido:
        return {
            **base,
            "entendeu": False,
            "contexto": contexto,
            "resposta": "Não identifiquei um filtro nessa pergunta. Tente citar um município, um perfil, uma condição, "
                        "um tempo de espera ou peça a definição de um termo, como “o que é APP?”.",
        }
    filtro = radar.FiltroFila(uf=uf, ibge=item.ibge, **{
        chave: (date.fromisoformat(valor) if chave.endswith("_desde") and isinstance(valor, str) else valor)
        for chave, valor in item.filtro.items()
    }).validar()
    parametros = dict(item.filtro)
    if item.ibge:
        parametros["ibge"] = item.ibge
    saida = {
        **base, "entendeu": True, "entendido": item.entendido, "filtros": parametros, "intencao": item.intencao,
        "contexto": {"filtros": item.filtro, "ibge": item.ibge},
    }
    if item.intencao == "ranking":
        linhas = radar.ranking(filtro, item.limite)
        if linhas:
            primeiro = linhas[0]
            quantidade = f"{primeiro['total']:,}".replace(",", ".")
            texto_resposta = f"{primeiro['municipio']} lidera, com {quantidade} imóveis nesse recorte."
        else:
            texto_resposta = "Nenhum município tem imóveis nesse recorte."
        return {**saida, "resposta": texto_resposta, "ranking": linhas}
    resultado = radar.fila(filtro, 1, item.limite)
    total = f"{resultado['total']:,}".replace(",", ".")
    local = f" em {item.municipio}" if item.municipio else f" em {uf}"
    texto_resposta = f"{total} imóveis{local} atendem a esses filtros."
    if any(chave in item.filtro for chave in ("analisado_desde", "alterado_desde")):
        with sicar.pool.connection() as conn:
            desde = conn.execute("SELECT min(dia) AS d FROM historico_imovel WHERE uf = %s", (uf,)).fetchone()["d"]
        texto_resposta += (
            f" O histórico de mudanças começou em {desde:%d/%m/%Y}." if desde
            else " O histórico de mudanças ainda não tem registros."
        )
    if item.intencao == "contagem":
        return {**saida, "resposta": texto_resposta, "total": resultado["total"], "itens": []}
    return {**saida, "resposta": texto_resposta, "total": resultado["total"], "itens": resultado["itens"]}
