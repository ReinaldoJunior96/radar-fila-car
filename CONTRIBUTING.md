# Como contribuir

1. Abra uma issue descrevendo o problema ou a proposta.
2. Mantenha a regra central: telas e rotas do Radar não podem chamar o SICAR.
3. Toda nova chamada externa deve passar por `FonteCar`, respeitando intervalo, orçamento e parada automática.
4. Mudanças em perfis exigem nova versão em `api/app/classificacao.py`, com regra, fonte e peso explícitos.
5. Rode os testes antes de enviar:

```bash
docker compose run --rm --no-deps -v "$PWD/api/tests:/app/tests:ro" -e PYTHONPATH=/app api \
  python -m unittest discover -s tests -t .
```

Não use termos que afirmem regularidade ou irregularidade de um imóvel. Não automatize o portal, não contorne captcha e não burle bloqueios.
