# Conformidade e segurança

Público: equipes técnicas, jurídicas e de segurança do MGI e do SFB.

## Dados pessoais (LGPD)

O sistema usa somente dados públicos do CAR publicados pelo SICAR e pela Consulta Pública.

- O índice guarda código do imóvel, município, situação, condição, área, módulos fiscais, datas, indicadores ambientais e limites simplificados. Não guarda nome, CPF, CNPJ ou contato de proprietários.
- A aplicação não tem cadastro de usuários, não usa cookies de rastreamento e não envia dados a terceiros. O mapa carrega imagens do OpenStreetMap.
- A lista de códigos enviada para a verificação de crédito não é gravada. Códigos de fora do índice usam o mesmo cache da Consulta, que guarda só dados públicos do imóvel.
- O Nginx registra o acesso no log padrão do contêiner, com IP, para os limites de uso. Em produção, a retenção deve seguir a política do órgão que hospedar o sistema.

Referência: [Lei nº 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm).

## Uso responsável da fonte

- A rotina faz uma chamada por vez, com intervalo, janela de horário e orçamento diário de chamadas e de volume.
- Respostas 401, 403, 429 ou páginas de acesso negado pausam a rotina por 24 horas.
- O projeto não automatiza o portal, não contorna captcha e não usa downloads protegidos.
- A aplicação se identifica no `User-Agent`.

## Segurança da aplicação

| Medida | Onde |
|---|---|
| Limite de requisições por IP, separado para leitura e para lote | `web/nginx.conf.template` |
| `Content-Security-Policy` sem scripts externos nem `eval` | Aplicação e versão incorporável |
| Incorporação só para origens autorizadas (`frame-ancestors`) | `EMBED_ORIGINS` |
| `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy` | `web/seguranca.conf` |
| Validação de todos os parâmetros, listas fechadas de filtros e consultas parametrizadas | `api/app/radar.py` |
| Assistente sem geração de SQL a partir do texto | `api/app/assistente.py` |
| Lotes limitados a 1.000 códigos e corpo limitado a 256 KB | API e Nginx |
| Banco sem porta exposta na demonstração pública | `compose.demo.yaml` |

Vulnerabilidades devem ser comunicadas como descrito em [SECURITY.md](../SECURITY.md).

## Interoperabilidade (e-PING)

O sistema segue padrões abertos recomendados pela [e-PING](https://eping.governoeletronico.gov.br/):

- API HTTP com JSON e documentação [OpenAPI](https://spec.openapis.org/oas/latest.html) em `/docs`.
- Limites em [GeoJSON (RFC 7946)](https://www.rfc-editor.org/rfc/rfc7946) e exportações em CSV com UTF-8.
- Coordenadas em SIRGAS 2000 (EPSG:4674), o referencial geodésico oficial do Brasil.
- Leitura da fonte pelo padrão [WFS da OGC](https://www.ogc.org/standards/wfs/).
- Banco PostgreSQL com PostGIS, ambos de código aberto.

## Dados abertos

- Os dados de origem são públicos e a aplicação os redistribui com a data da última sincronização.
- Rotas de leitura e CSV permitem reutilização sem cadastro.
- Os resumos por município podem ser publicados no [Portal de Dados Abertos](https://dados.gov.br/) se o órgão responsável decidir.

## Código aberto

Licença Apache-2.0, testes automatizados no GitHub Actions e instruções em [CONTRIBUTING.md](../CONTRIBUTING.md).

## Acessibilidade

A interface usa HTML semântico, rótulos em todos os campos, navegação por teclado, foco visível, `aria-live` nas respostas, textos alternativos e tabelas para os dados dos gráficos. Os níveis de atenção usam ícone e texto, não só cor. Layout testado em 390 px de largura.

Referência: [Modelo de Acessibilidade em Governo Eletrônico (eMAG)](https://www.gov.br/governodigital/pt-br/acessibilidade-e-usuario/acessibilidade-digital/modelo-de-acessibilidade). Não foi feita auditoria formal de acessibilidade.
