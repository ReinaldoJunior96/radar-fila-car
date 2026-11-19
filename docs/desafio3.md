# Atendimento ao Desafio 3

Público: avaliadores do InovaCAR.

Cada item do edital, onde ele está no sistema e como conferir. Medições no Maranhão, em ambiente local, em 18 e 19/11/2026.

## Resultados esperados

| Item do edital | Como o sistema atende | Evidência |
|---|---|---|
| Democratizar o acesso aos dados | Radar, Crédito e Assistente em português, sem conhecimento de WFS | Abas da aplicação |
| Reduzir banda e carga sobre o SICAR | Telas leem o índice local; a rotina sincroniza com orçamento | 300 leituras do Radar e nenhuma chamada; atualização diária com 2 chamadas e 27 KB |
| Agilizar a análise de crédito | Verificação de até 1.000 códigos com pontos de atenção e CSV | 1.000 códigos em 31 ms, nenhuma chamada ao SICAR |

## Características da solução

| Item do edital | Como o sistema atende | Onde |
|---|---|---|
| Código aberto | Apache-2.0, CI pública | [Repositório](https://github.com/ReinaldoJunior96/radar-fila-car) |
| Software e MVP | Aplicação em Docker Compose, com demonstração pronta | [README](../README.md) |
| Ciência de dados | 20 perfis explicáveis, prioridade sugerida e K-Means com qualidade medida | [Metodologia](metodologia.md) |
| APIs para consultas pontuais | Imóvel, lote, fila, crédito, mapa, linha do tempo | `/docs` |
| Filtros antes do download | Perfil, condição, situação, tipo, tempo, área, grupo, município, área do mapa e movimento recente | Radar e `GET /api/radar/fila` |
| “Analisados no último mês” | Filtro por histórico de mudanças de condição | Radar, Assistente e `analisado_desde` |
| “Imóveis com área a recompor” | Perfil APP a recompor | Radar e `perfis=app_recompor` |
| Classificação e qualificação | Perfis com regra, fonte e peso públicos | `GET /api/perfis` |
| Agrupamento | K-Means com 7 grupos, silhueta 0,33 e estabilidade 0,74 | Radar, seção Padrões |
| Painel de gargalos no ciclo de vida | Etapas, tempo desde a criação, coortes, ranking, linha do tempo por etapa e mudanças diárias | Radar |
| Chatbot com linguagem natural | Assistente em conversa, com contexto e definições da central | Aba Assistente |
| Hub de conhecimento | Guias, FAQ, glossário, dicionário, metodologia, limites, biblioteca técnica, legislação | Aba Conhecimento |

## Perfil técnico pedido

| Item do edital | Como o sistema atende | Evidência |
|---|---|---|
| Reestruturação do backend, não só interface | Modelo de leitura separado, porta `FonteCar`, sincronização incremental | [Arquitetura](arquitetura.md) |
| Otimização do banco | Índices GIN, GiST e compostos; agregados pré-calculados | Fila com perfis em 22,7 ms |
| Ganho real de desempenho | Leituras locais em milissegundos | Resumo em 2,4 ms; área do mapa em 49 ms |
| APIs geoespaciais | Limites em GeoJSON e filtro por retângulo do mapa | `GET /api/radar/mapa`, `oeste`, `sul`, `leste`, `norte` |
| Indexação espacial avançada | PostGIS com GiST, SIRGAS 2000 | Consulta por área em 12 ms no banco |
| Arquitetura de cache | Índice local, cache do Nginx e cache das consultas sob demanda | `X-Cache-Status`, `GET /api/cache/metricas` |
| Microsserviços | Serviços separados de API, sincronização, banco e proxy | `compose.yaml` |
| Volume de dados | 419.401 imóveis em 1h52, com 53,8 MB | [README](../README.md) |
| Privacidade e segurança | Sem dados pessoais, CSP, limites por IP | [Conformidade](conformidade.md) |
| LGPD, e-PING, dados abertos | Seção própria | [Conformidade](conformidade.md) |
| Aplicabilidade no portal | Versão incorporável e contrato de fonte trocável | [Integração](integracao-mgi.md) |

## O que ainda depende de fora do projeto

- O histórico de mudanças começa na primeira atualização diária. Antes disso, o filtro “analisados no último mês” não tem dados, porque o SICAR público não publica a data das análises.
- O Assistente interpreta perguntas por regras. É previsível e não inventa dados, mas não entende qualquer formulação.
- Vídeos e pílulas de conhecimento ainda não foram produzidos.
- Escala nacional e integração ao portal dependem de acesso interno e de decisão do MGI.
