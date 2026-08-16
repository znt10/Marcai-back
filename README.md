# back

O backend Django deste projeto: API que atende `<slug>.<DOMINIO_BASE>` (uma
barbearia por subdominio), tarefas assíncronas (Celery `worker`/`beat`) e o
webhook/serviço do WhatsApp (Evolution API). Roda em processo separado do
`front` (Next.js) e fala com o mesmo Postgres, mas **não é dono do schema**
desse banco — ver a regra no fim deste documento antes de tudo o mais.

Esta é a raiz que a spec (§5) exige que suba, teste e vá para produção
**sozinha**, sem o `front` ao lado. As instruções abaixo foram testadas
literalmente neste repositório — se algum comando aqui não funcionar mais,
conserte o comando, não a memória de quem lê.

## Rede

Os dois `docker-compose.yml` (deste repo e o do `front`) declaram a rede
`brutus` como `external: true` de propósito: ela é criada à mão e vive mais
que qualquer um dos dois composes, porque os dois times de containers
(Postgres, Redis, Evolution) são compartilhados entre back e front. Se um
compose criasse a rede, ela morreria no `down` de quem a criou e o outro lado
perderia o banco no meio do trabalho.

Antes de subir qualquer coisa, uma vez por máquina:

```
docker network create brutus
```

(Erro "network with name brutus already exists" na segunda vez em diante é
esperado e inofensivo — a rede já existe, não recrie.)

## Variáveis de ambiente

Copie o exemplo e preencha:

```
cp .env.example .env
```

O `.env.example` documenta cada variável. As três que só importam para rodar
`manage.py` diretamente no host (fora de container) — `PGDATABASE`,
`PGHOST`, `PGPORT` — não alimentam o `docker-compose.yml`: lá `api`, `worker`
e `beat` já têm `PGHOST=db`/`PGPORT=5432` escritos direto no `environment:`
de cada serviço. `pytest` também não lê essas três do `.env`: ele define as
suas próprias (`brutus_test`, ver `pytest.ini`) independente do que estiver
aqui.

## Subir

```
docker compose up -d --build
```

Isso sobe `db` (Postgres, publicado em `localhost:5433`), `redis`,
`evolution` (WhatsApp), `api` (Django em `localhost:8000`), `worker` e
`beat`. Desde a fatia 7, `worker`/`beat` também fazem o que `agendador` e
`zelador` faziam (lembrete, healthcheck do WhatsApp e poda do histórico) —
os dois contêineres separados saíram do compose. Confira o estado com:

```
docker compose ps
```

Se um `docker compose run` ou `up` **travar em silêncio** em vez de dar erro,
o sintoma de sempre é o `db` tendo saído sozinho antes — confira
`docker compose ps` primeiro; se `db` não estiver `healthy`, é por aí.

## Rodar os testes

Duas formas.

### Em Docker (preferida, não precisa de venv)

```
docker compose run --rm api pytest -q
```

Isso roda o `api` já com `PGHOST=db`/`PGPORT=5432` (do `environment:` do
serviço) contra o `brutus_test` do próprio Postgres do compose.

### No host

```
./.venv/Scripts/python.exe -m pytest -v
```

(Não existe `python` funcional no PATH deste ambiente Windows — o stub da
Microsoft Store intercepta o nome sem rodar nada; use sempre o caminho
absoluto do `.venv`.) Neste modo `pytest.ini` aponta para
`localhost:5433` (a porta publicada do `db` do compose) por padrão — não é
preciso exportar nada a mais além de já ter feito `docker compose up`.

### Pré-requisito dos dois modos: `brutus_test` migrado pelo Prisma

Este repositório **não cria tabela nenhuma** em `brutus_test` (mesma regra
do próximo parágrafo, aplicada ao banco de teste). Quem migra `brutus_test`
é o Prisma, do lado do `front`. Antes da primeira vez que rodar os testes
aqui, rode — **no repositório `front`**, com o `back` já de pé (é de lá que
`localhost:5433` responde):

```
DATABASE_URL="postgresql://brutus_owner:owner@localhost:5433/brutus_test" npx prisma migrate deploy
```

Sem isso, `pytest` falha com `relation "Barbearia" does not exist` num banco
que existe e está de pé — a tabela é que não foi criada ainda. Isto não é um
passo deste repositório escondido em outro lugar por acidente: é a fronteira
da spec (§8) sendo respeitada — ver a regra abaixo.

## Regra que vale mais que todas as outras deste documento

**Este repositório nunca roda DDL em `brutus` nem em `brutus_test`.** Quem
cria e migra tabela nesses dois bancos é o Prisma, do lado do `front`. Isso
está refletido em três lugares que não devem divergir entre si:

- `INSTALLED_APPS` (`backend/backend/settings.py`) é deliberadamente mínimo —
  sem `contrib.admin`, `contrib.auth`, `contrib.contenttypes` nem `sessions`,
  porque cada um deles criaria tabela própria num banco que não é seu dono.
- `pytest.ini` roda com `--no-migrations`.
- `entrypoint.sh` espera o banco responder e para por aí — não chama
  `manage.py migrate`.

Se alguém propuser rodar `manage.py migrate` ou `manage.py makemigrations`
contra `brutus`/`brutus_test`, ou adicionar um app do Django que crie tabela
própria, a resposta é não — mesmo que a razão pareça boa (e normalmente
parece: cada um dos apps acima existe por um motivo legítimo em outro
contexto). Migração legítima deste schema vem do Prisma, no `front`.
