"""Agrupamento exploratório dos cadastros, executado na sincronização."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from . import classificacao

MINIMO_REGISTROS = 2000
AMOSTRA_TREINO = 50000
AMOSTRA_SILHUETA = 5000
FAIXA_K = range(3, 8)
SEMENTES = (11, 23, 47)
VARIAVEIS = [
    "log_area", "log_modulos", "anos", "sem_analise", "analisado",
    "app_recompor", "sobreposicoes", "retificacoes", "pendente",
]
ROTULOS = {
    "log_area": ("Áreas maiores", "Áreas menores"),
    "log_modulos": ("Mais módulos fiscais", "Menos módulos fiscais"),
    "anos": ("Cadastros antigos", "Cadastros recentes"),
    "sem_analise": ("Sem análise concluída", None),
    "analisado": ("Já analisados", None),
    "app_recompor": ("Com APP a recompor", None),
    "sobreposicoes": ("Com sobreposições", None),
    "retificacoes": ("Mais retificações", None),
    "pendente": ("Cadastro pendente", None),
}


def _vetor(linha: dict[str, Any], hoje: date) -> list[float]:
    grupo = linha.get("condicao_grupo") or ""
    return [
        float(np.log1p(max(linha.get("area_ha") or 0, 0))),
        float(np.log1p(max(linha.get("modulos") or 0, 0))),
        classificacao.idade_anos(linha, hoje) or 0.0,
        float("sem_analise" in (linha.get("perfis") or [])),
        float(grupo.startswith("analisado")),
        float(bool(linha.get("tem_app_recompor"))),
        float(len(linha.get("sobreposicoes") or [])),
        float(linha.get("retificacoes") or 0),
        float(linha.get("status") == "PE"),
    ]


def nomear(desvios: np.ndarray) -> str:
    """Nomeia o grupo pelas duas características que mais o distinguem da base."""
    partes: list[str] = []
    for indice in np.argsort(-np.abs(desvios)):
        valor = float(desvios[indice])
        if abs(valor) < 0.5:
            break
        positivo, negativo = ROTULOS[VARIAVEIS[indice]]
        rotulo = positivo if valor > 0 else negativo
        if rotulo:
            partes.append(rotulo)
        if len(partes) == 2:
            break
    return " · ".join(partes) or "Próximo da média"


def _escolher_k(dados: np.ndarray, rng: np.random.Generator) -> tuple[int, float]:
    amostra = dados[rng.choice(len(dados), min(AMOSTRA_SILHUETA, len(dados)), replace=False)]
    melhor = (FAIXA_K[0], -1.0)
    for k in FAIXA_K:
        rotulos = KMeans(n_clusters=k, n_init=5, random_state=SEMENTES[0]).fit_predict(amostra)
        nota = float(silhouette_score(amostra, rotulos))
        if nota > melhor[1]:
            melhor = (k, nota)
    return melhor


def agrupar(conn: psycopg.Connection[Any], uf: str, hoje: date | None = None) -> dict[str, Any] | None:
    hoje = hoje or date.today()
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT cod_imovel, area_ha, modulos, data_criacao, condicao_grupo, status, perfis,
                      tem_app_recompor, sobreposicoes, retificacoes
               FROM indice_imovel WHERE uf = %s ORDER BY cod_imovel""",
            (uf,),
        )
        linhas = cursor.fetchall()
    if len(linhas) < MINIMO_REGISTROS:
        return None
    bruto = np.array([_vetor(linha, hoje) for linha in linhas], dtype=float)
    escala = StandardScaler().fit(bruto)
    dados = escala.transform(bruto)
    rng = np.random.default_rng(SEMENTES[0])
    treino = dados[rng.choice(len(dados), min(AMOSTRA_TREINO, len(dados)), replace=False)]
    k, silhueta = _escolher_k(treino, rng)
    modelos = [KMeans(n_clusters=k, n_init=5, random_state=seed).fit(treino) for seed in SEMENTES]
    previsoes = [modelo.predict(dados) for modelo in modelos]
    estabilidade = min(
        float(adjusted_rand_score(previsoes[0], outra)) for outra in previsoes[1:]
    )
    atuais = previsoes[0]
    ordem = np.argsort(-np.bincount(atuais, minlength=k))
    novo = np.empty(k, dtype=int)
    novo[ordem] = np.arange(k)
    finais = novo[atuais]
    qualidade = {
        "k": k,
        "silhueta": round(silhueta, 3),
        "estabilidade_ari": round(estabilidade, 3),
        "registros": len(linhas),
        "amostra_treino": len(treino),
        "variaveis": VARIAVEIS,
    }
    grupos = []
    for grupo in range(k):
        mascara = finais == grupo
        parte = bruto[mascara]
        desvios = dados[mascara].mean(axis=0)
        grupos.append(
            (
                uf, grupo, nomear(desvios), int(mascara.sum()),
                json.dumps(
                    {
                        "area_mediana_ha": round(float(np.expm1(np.median(parte[:, 0]))), 1),
                        "modulos_medianos": round(float(np.expm1(np.median(parte[:, 1]))), 2),
                        "anos_medianos": round(float(np.median(parte[:, 2])), 1),
                        "sem_analise_pct": round(float(parte[:, 3].mean() * 100), 1),
                        "analisado_pct": round(float(parte[:, 4].mean() * 100), 1),
                        "app_recompor_pct": round(float(parte[:, 5].mean() * 100), 1),
                        "sobreposicao_pct": round(float((parte[:, 6] > 0).mean() * 100), 1),
                        "pendente_pct": round(float(parte[:, 8].mean() * 100), 1),
                    }
                ),
                json.dumps(qualidade),
            )
        )
    with conn.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE entrada_grupo (codigo text, grupo integer) ON COMMIT DROP")
        with cursor.copy("COPY entrada_grupo FROM STDIN") as copy:
            for linha, grupo in zip(linhas, finais.tolist()):
                copy.write_row((linha["cod_imovel"], grupo))
        cursor.execute(
            """UPDATE indice_imovel AS i SET grupo = e.grupo FROM entrada_grupo AS e
               WHERE e.codigo = i.cod_imovel AND i.grupo IS DISTINCT FROM e.grupo"""
        )
        cursor.execute("DROP TABLE entrada_grupo")
        cursor.execute("DELETE FROM indice_grupo WHERE uf = %s", (uf,))
        cursor.executemany(
            """INSERT INTO indice_grupo (uf, grupo, rotulo, total, caracteristicas, qualidade)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)""",
            grupos,
        )
    return qualidade
