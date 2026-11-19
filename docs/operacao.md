# Operação

Público: quem instala e mantém o sistema.

## Subir a aplicação
```bash
cp .env.example .env
docker compose up -d --build
```
Aplicação em `http://localhost:8080` e API em `http://localhost:8000/docs`.

## Carregar o índice
Teste primeiro um município:
```bash
docker compose run --rm sync python -m app.sync_indice --uf MA --municipio "Itapecuru Mirim" --retificacoes
```
Depois carregue o estado:
```bash
docker compose run --rm sync python -m app.sync_indice --uf MA --carga --indicadores --retificacoes
```
Se o orçamento do dia acabar, repita o comando no dia seguinte. A rotina continua do último município concluído.

Os limites dos imóveis ficam em tarefa própria, de menor prioridade. A primeira passada lê um município por chamada, cerca de 50 MB no Maranhão. Depois, só os imóveis alterados são relidos:
```bash
docker compose run --rm sync python -m app.sync_indice --uf MA --geometrias
```

## Rotina automática
```bash
docker compose --profile sync up -d sync
```
Fora da janela configurada a rotina não consulta a fonte. Na demonstração pública, `compose.demo.yaml` já inicia esse serviço.

| Tarefa | Frequência | Comando manual |
|---|---|---|
| Alterações | Diária | `--diario` |
| Indicadores ambientais | Semanal | `--indicadores` |
| Conferência de totais e remoções | Semanal | `--conferir` |
| Retificações | Mensal | `--retificacoes` |
| Limites dos imóveis | Até concluir, depois só alterados | `--geometrias` |
| Recarga gradual | Mensal | Automática |
| Perfis, resumos e agrupamento | Após cada tarefa | `--recalcular` |

## Proteções
Uma chamada por vez, intervalo configurável, janela de horário, orçamento diário de chamadas (`SYNC_ORCAMENTO_DIARIO`, 600) e de volume (`SYNC_ORCAMENTO_MB_DIARIO`, 300 MB), retomada por município. Respostas 401, 403, 429 ou uma página de acesso negado pausam a UF por 24 horas. Três falhas temporárias seguidas pausam por 1 hora.

Para conferir: `GET /api/sincronizacao/status`.

Comandos manuais não respeitam a janela. Evite rodá-los entre 01:00 e 05:16, horário observado da extração oficial.

Antes de remover uma pausa, investigue o motivo registrado. Não contorne bloqueios da fonte.

## Testes e medição
```bash
docker compose run --rm --no-deps -v "$PWD/api/tests:/app/tests:ro" -e PYTHONPATH=/app api \
  python -m unittest discover -s tests -t .
python3 benchmarks/medir_camada.py
```
