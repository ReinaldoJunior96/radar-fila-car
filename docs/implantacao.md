# Publicar a demonstração numa VPS

Este guia sobe a demonstração pública com HTTPS. Para isso, usa `compose.demo.yaml` e um endereço gratuito do [sslip.io](https://sslip.io).

## Requisitos

- Linux com Docker e o plugin Compose.
- Portas 80 e 443 livres. Se estiverem ocupadas, veja [Outro site na mesma VPS](#outro-site-na-mesma-vps).
- Memória: 4 GB funcionam, mas 8 GB é o confortável. Disco: cerca de 4 GB.

Consumo medido com o Maranhão inteiro (419 mil imóveis):

| Serviço | Memória em uso | Limite padrão |
|---|---|---|
| Banco (PostGIS) | ~520 MB | 1,5 GB |
| API | ~80 MB | 512 MB |
| Sincronização | parada fora da janela | 1,5 GB |
| Site (Nginx) e Caddy | ~15 MB cada | 128 MB cada |

## 1. Endereço

O sslip.io responde com o IP que estiver escrito no nome. Por isso não há cadastro nem configuração de DNS. Basta trocar os pontos do IP da VPS por hífens:

```text
IP da VPS:  203.0.113.10
Endereço:   203-0-113-10.sslip.io
```

O Caddy emite sozinho o certificado HTTPS para esse nome.

## 2. Código e configuração

```bash
git clone https://github.com/ReinaldoJunior96/radar-fila-car.git
cd radar-fila-car
cp .env.demo.example .env.demo
openssl rand -hex 24   # use o resultado em POSTGRES_PASSWORD
nano .env.demo         # preencha DEMO_SITE e POSTGRES_PASSWORD
```

## 3. Dados iniciais

Há dois caminhos:

| Caminho | Tempo | Chamadas ao SICAR |
|---|---|---|
| A. Copiar o índice de uma instalação existente | minutos | nenhuma |
| B. Deixar a VPS sincronizar sozinha | primeira noite, das 20:00 às 00:30 | cerca de 600 |

O caminho A evita repetir a carga na fonte.

### A. Copiar o índice

Na máquina que já tem o índice (cerca de 40 MB):

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner \
  -t indice_imovel -t municipio_ref -t indice_perfil -t indice_grupo -t sync_estado -t sync_execucao \
  -t sync_checkpoint -t resumo_municipio -t historico_imovel -t geometria_imovel -t snapshot_municipio' > indice.dump
scp indice.dump usuario@203.0.113.10:~/radar-fila-car/
```

Na VPS, suba só o banco e restaure:

```bash
docker compose -f compose.demo.yaml --env-file .env.demo up -d --build db
docker compose -f compose.demo.yaml --env-file .env.demo exec -T db \
  sh -c 'psql -U carapp -d car -c "create extension if not exists postgis" && pg_restore -U carapp -d car --no-owner --exit-on-error' < indice.dump
```

### B. Sincronizar na VPS

Não precisa de nenhum passo extra: o serviço `sync` começa a carga na primeira janela noturna. Até lá, o Radar avisa que o índice ainda não foi carregado.

## 4. Subir tudo

```bash
docker compose -f compose.demo.yaml --env-file .env.demo up -d --build
docker compose -f compose.demo.yaml --env-file .env.demo ps
```

Abra `https://203-0-113-10.sslip.io`. O primeiro acesso pode levar alguns segundos enquanto o certificado é emitido.

## Atualizar

```bash
git pull
docker compose -f compose.demo.yaml --env-file .env.demo up -d --build
```

O banco fica no volume `car_demo_pgdata` e não se perde ao reconstruir as imagens.

## Outro site na mesma VPS

Se outro proxy (Nginx, Caddy, Traefik) já usa as portas 80 e 443, não suba o Caddy deste projeto:

```bash
docker compose -f compose.demo.yaml --env-file .env.demo up -d --build db api sync web
```

O site fica disponível só dentro da máquina, em `127.0.0.1:8088`. No proxy existente, crie um site para o endereço do sslip.io encaminhando para essa porta. Exemplo para Nginx com Certbot:

```nginx
server {
    server_name 203-0-113-10.sslip.io;
    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Depois rode `certbot --nginx -d 203-0-113-10.sslip.io`.

## Limites do sslip.io

É um serviço gratuito de terceiros. Se ele ficar fora do ar, o endereço para de resolver, mas a aplicação continua de pé na VPS. Para uso permanente, aponte um domínio próprio para o IP e troque `DEMO_SITE`.
