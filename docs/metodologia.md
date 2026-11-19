# Metodologia

Público: especialistas que vão revisar os critérios.

## Tempo de fila
O dado público não informa quando o cadastro entrou em cada etapa. O sistema usa o tempo desde `dat_criacao` como aproximação.

## Perfis
A lista oficial do sistema está em `GET /api/perfis`, com regra, fonte, peso e versão. Um imóvel pode ter vários perfis.

## Prioridade sugerida
É a soma dos pesos dos perfis, limitada a 100. Cadastros cancelados recebem zero. Os pesos são uma proposta inicial e devem ser calibrados por especialistas e pelos órgãos estaduais. A prioridade não indica regularidade ou irregularidade.

## Sobreposições e APP a recompor
Sobreposição usa indicadores oficiais maiores que zero nas camadas `iru`, `ast` e `pct`. APP a recompor indica presença do imóvel nas camadas `app_escadinha_*`. O sistema não refaz essas análises; o único cruzamento geoespacial próprio é o de CARs entre si, descrito abaixo.

## Sobreposição entre CARs

Os limites de CARs ativos da mesma UF são cruzados entre si no índice espacial local, sem chamadas ao SICAR. Pares em que a área comum cobre menos de 10% dos dois lados são descartados, para não confundir divisa mal digitalizada com sobreposição. Três perfis resultam do cruzamento:

| Perfil | Regra | Peso |
|---|---|---|
| Cobre outros cadastros | Imóvel rural (IRU) que contém 90% ou mais da área de 3 ou mais outros CARs ativos | 20 |
| Mesma área de outro CAR | Outro CAR ativo cobre 90% ou mais deste limite, e este cobre 90% ou mais do outro | 15 |
| Dentro de outro CAR | 50% ou mais do limite está dentro de outro CAR ativo que não é assentamento | 5 |

Assentamentos (AST) que contêm lotes não entram no primeiro perfil, porque esse é o arranjo esperado. O padrão "um CAR grande sobre vários pequenos" aparece em estudos sobre grilagem por meio do CAR, mas há explicações legítimas, como desmembramentos com cadastro antigo ativo ou áreas coletivas cadastradas como imóvel rural. Os perfis indicam o que vale verificar; não afirmam irregularidade nem dizem quem tem a posse. Os dados públicos não trazem nome, CPF ou CNPJ.

O cálculo só vale para os municípios cujos limites já estão no índice espacial e roda na rotina noturna, antes da reclassificação.

## Agrupamento
K-Means com variáveis padronizadas: área e módulos em escala logarítmica, anos desde a criação, sem análise, analisado, APP a recompor, número de sobreposições, retificações e pendência. O número de grupos, de 3 a 7, é escolhido pela silhueta em amostra. A estabilidade é medida pelo índice de Rand ajustado entre sementes. Os grupos são exploratórios.

## Assistente
Interpreta a pergunta por regras e transforma o texto em filtros permitidos. Não usa modelo generativo e não escreve SQL a partir do texto.
Mantém o contexto da pergunta anterior: “e só em Itapecuru Mirim?” reaproveita os filtros já entendidos. Perguntas como “o que é módulo fiscal?” são respondidas com o glossário, o dicionário de dados e os perfis da central de conhecimento, sempre com a fonte.

## Histórico e linha do tempo
O SICAR público não informa a data em que cada imóvel mudou de etapa. A partir da primeira atualização diária, a rotina registra em `historico_imovel` cada entrada, saída, mudança de condição e mudança de situação, com o dia em que foi vista. A carga inicial não gera eventos, para não confundir o primeiro retrato com mudanças. O filtro “concluíram análise nos últimos 30 dias” usa esse histórico. A linha do tempo combina o histórico com a fotografia diária de cada etapa.

## Verificação para crédito
Cada perfil vira um ponto de atenção de nível alto, atenção ou informativo, com a fonte. Alto: cadastro cancelado ou suspenso, sobreposição com área embargada ou terra indígena. O resultado do imóvel é o do ponto mais grave. Códigos de estados fora do índice são buscados ao vivo e recebem o aviso de que os indicadores ambientais não foram verificados. A verificação não substitui as consultas exigidas pelas normas de crédito rural.

## Índice espacial
Os limites são simplificados com tolerância de 0,00002 grau, cerca de 2 metros, corrigidos com `ST_MakeValid` e guardados em SIRGAS 2000 (EPSG:4674) com índice GiST. Em Itapecuru Mirim, a soma das áreas dos limites ficou 0,06% acima da soma das áreas declaradas. O filtro por área do mapa usa `ST_Intersects` com o retângulo visível.
