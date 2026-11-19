# Arquitetura

Público: equipes técnicas do MGI e de órgãos estaduais.

```text
Serviços do SICAR ──(rotina com orçamento)──> sync ──> índice PostGIS ──> API ──> Radar, Crédito, Assistente, embed
        ▲                                                                     │
        └────────(detalhe e Consulta, sob demanda e com cache)────────────────┘
```

| Componente | Função | Chama o SICAR? |
|---|---|---|
| `fonte.py` | Contrato `FonteCar` e implementação pelos serviços públicos | Sim, só na rotina |
| `sync_indice.py` | Carga, atualização diária, conferência e recarga | Sim, com limites |
| `indice.py` | Tabelas, gravação, resumos e fotografias diárias | Não |
| `classificacao.py` | Perfis e prioridade sugerida | Não |
| `agrupamento.py` | K-Means exploratório, executado na rotina | Não |
| `radar.py`, `assistente.py` | Leitura do índice, histórico e índice espacial | Não |
| `credito.py` | Verificação em lote para crédito rural | Só para códigos fora do índice, com cache |
| `sicar.py` | Consulta sob demanda com cache | Sim, com cache |

Os atributos e os limites simplificados ficam no índice local. O cadastro completo, com as camadas ambientais, continua vindo da fonte oficial quando alguém abre a Consulta.

Principais tabelas: `indice_imovel`, `indice_perfil`, `indice_grupo`, `municipio_ref`, `resumo_municipio`, `snapshot_municipio`, `historico_imovel`, `geometria_imovel`, `sync_estado`, `sync_execucao` e `sync_checkpoint`.

## Padrões adotados

| Padrão | Onde |
|---|---|
| Modelo de leitura separado (CQRS de leitura) | As telas leem `indice_imovel` e os resumos; só a rotina escreve |
| Porta e adaptador | `FonteCar` define o contrato; `ServicosPublicosCar` é uma implementação trocável |
| Sincronização incremental com checkpoint | `sync_checkpoint` e paginação por código maior que o último |
| Orçamento e disjuntor | Limites de chamadas e de volume, pausa em bloqueio ou falhas seguidas |
| Cache em camadas | Índice local, cache HTTP no Nginx e cache das consultas sob demanda |
| Agregados pré-calculados | `resumo_municipio` e `snapshot_municipio` |

## Desempenho e índices

| Consulta | Índice | Resultado medido |
|---|---|---|
| Fila por perfis | GIN em `perfis` | 22,7 ms |
| Área visível do mapa | GiST em `geometria_imovel.geom` | 12 ms no banco, 49 ms na API |
| Limites de um município | GiST e `ibge` | 4.967 limites em 97 ms e 306 KB com gzip |
| Crédito, 1.000 códigos | Chave primária | 31 ms e nenhuma chamada ao SICAR |

## Segurança
Nginx aplica limites de requisição por IP, CSP, `nosniff`, `Referrer-Policy` e `Permissions-Policy`. A incorporação só é permitida para as origens em `EMBED_ORIGINS`. Detalhes em [Conformidade](conformidade.md).
