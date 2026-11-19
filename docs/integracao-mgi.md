# Integração com o portal do CAR

Público: equipe técnica do MGI.

## Caminho proposto
1. **Incorporar:** publicar o Radar em infraestrutura aprovada e incluir `/embed/radar` no portal.
2. **Trocar a origem:** implementar `FonteCar` com leitura de uma réplica interna ou de eventos de alteração.
3. **Reduzir defasagem:** substituir a varredura diária por mudanças publicadas pelo próprio SICAR.
4. **Validar:** revisar perfis e pesos com especialistas e órgãos estaduais.

## Incorporação
```html
<iframe src="https://SEU-DOMINIO/embed/radar" title="Radar da Fila do CAR" width="100%" height="1200"></iframe>
```
Defina os sites autorizados:
```bash
EMBED_ORIGINS="'self' https://www.car.gov.br https://consulta.car.gov.br"
```

## Contrato da fonte
Uma nova fonte implementa `municipios`, `cadastro_municipio`, `total_municipio`, `total_alterados`, `alterados`, `codigos_recompor`, `sobreposicoes` e `retificacoes`, definidos em `api/app/fonte.py`. Radar, classificação e API não mudam.

## Dados desejáveis da fonte interna
- Data de entrada em cada etapa da análise, para medir o tempo real de fila.
- Histórico de mudanças de condição.
- Evento de alteração por imóvel, evitando consultas repetidas.
- Autorização formal para os indicadores que forem exibidos.

## API
A documentação OpenAPI fica em `/docs`.
```bash
curl "https://SEU-DOMINIO/api/radar/resumo?uf=MA"
curl "https://SEU-DOMINIO/api/radar/fila?uf=MA&perfis=fila_5_anos,app_recompor&por_pagina=25"
curl "https://SEU-DOMINIO/api/assistente?uf=MA&q=quantos%20imoveis%20sem%20analise"
```
A integração efetiva depende de decisão e autorização do governo.
