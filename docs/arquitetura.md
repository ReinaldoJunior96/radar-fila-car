# Arquitetura

Público: equipes técnicas do MGI e de órgãos estaduais.

```text
Serviços do SICAR ──(rotina com orçamento)──> sync ──> índice PostgreSQL ──> API ──> Radar, Assistente, embed
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
| `radar.py`, `assistente.py` | Leitura do índice | Não |
| `sicar.py` | Consulta sob demanda com cache | Sim, com cache |

O índice não guarda geometrias. Mapas de imóveis e camadas continuam vindo da fonte oficial quando alguém abre a Consulta ou o cadastro completo.

Principais tabelas: `indice_imovel`, `indice_perfil`, `indice_grupo`, `municipio_ref`, `resumo_municipio`, `snapshot_municipio`, `sync_estado`, `sync_execucao` e `sync_checkpoint`.
