#!/usr/bin/env python3
"""Mede o Radar e o custo da sincronização sem gerar consultas ao SICAR.

Uso: python3 benchmarks/medir_camada.py [URL_BASE] [REPETICOES]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
REPETICOES = int(sys.argv[2]) if len(sys.argv) > 2 else 50
ROTAS = {
    "resumo": "/api/radar/resumo?uf=MA",
    "municipios": "/api/radar/municipios?uf=MA",
    "fila_sem_filtro": "/api/radar/fila?uf=MA&por_pagina=25",
    "fila_perfis": "/api/radar/fila?uf=MA&perfis=fila_5_anos,app_recompor&por_pagina=25",
    "exportacao": "/api/radar/fila/export?uf=MA&perfis=app_recompor",
    "assistente": "/api/assistente?uf=MA&q=quantos%20im%C3%B3veis%20sem%20an%C3%A1lise%20h%C3%A1%20mais%20de%205%20anos",
}


def ler(caminho: str) -> bytes:
    with urllib.request.urlopen(BASE + caminho, timeout=60) as resposta:
        return resposta.read()


def json_de(caminho: str) -> dict:
    return json.loads(ler(caminho))


antes = json_de("/api/cache/metricas")["chamadas_ao_sicar"]
rotas = {}
for nome, caminho in ROTAS.items():
    tempos, tamanho = [], 0
    for _ in range(REPETICOES):
        inicio = time.perf_counter()
        tamanho = len(ler(caminho))
        tempos.append((time.perf_counter() - inicio) * 1000)
    tempos.sort()
    rotas[nome] = {
        "mediana_ms": round(statistics.median(tempos), 1),
        "p95_ms": round(tempos[int(len(tempos) * 0.95) - 1], 1),
        "bytes": tamanho,
    }
status = json_de("/api/sincronizacao/status")
print(json.dumps({
    "repeticoes_por_rota": REPETICOES,
    "rotas": rotas,
    "requisicoes": REPETICOES * len(ROTAS),
    "chamadas_ao_sicar_durante_o_teste": json_de("/api/cache/metricas")["chamadas_ao_sicar"] - antes,
    "sincronizacao": status["execucoes"],
}, ensure_ascii=False, indent=2))
