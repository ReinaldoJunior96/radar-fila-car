# Metodologia

Público: especialistas que vão revisar os critérios.

## Tempo de fila
O dado público não informa quando o cadastro entrou em cada etapa. O sistema usa o tempo desde `dat_criacao` como aproximação.

## Perfis
A lista oficial do sistema está em `GET /api/perfis`, com regra, fonte, peso e versão. Um imóvel pode ter vários perfis.

## Prioridade sugerida
É a soma dos pesos dos perfis, limitada a 100. Cadastros cancelados recebem zero. Os pesos são uma proposta inicial e devem ser calibrados por especialistas e pelos órgãos estaduais. A prioridade não indica regularidade ou irregularidade.

## Sobreposições e APP a recompor
Sobreposição usa indicadores oficiais maiores que zero nas camadas `iru`, `ast` e `pct`. APP a recompor indica presença do imóvel nas camadas `app_escadinha_*`. O sistema não refaz análise geoespacial.

## Agrupamento
K-Means com variáveis padronizadas: área e módulos em escala logarítmica, anos desde a criação, sem análise, analisado, APP a recompor, número de sobreposições, retificações e pendência. O número de grupos, de 3 a 7, é escolhido pela silhueta em amostra. A estabilidade é medida pelo índice de Rand ajustado entre sementes. Os grupos são exploratórios.

## Assistente
Interpreta a pergunta por regras e transforma o texto em filtros permitidos. Não usa modelo generativo e não escreve SQL a partir do texto.
