# back

O backend Django deste projeto: API que atende `<slug>.<DOMINIO_BASE>` (uma
barbearia por subdominio), tarefas assíncronas (Celery `worker`/`beat`) e o
webhook/serviço do WhatsApp (Evolution API). Roda em processo separado do
`front` (Next.js) e fala com o mesmo Postgres — e **é quem cria e migra o
schema** desse banco, desde a fatia 1. Ver "Quem migra este banco", perto do
fim deste documento, antes de propor `makemigrations` ou um app novo em
`INSTALLED_APPS`.

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

## Popular o banco (dev)

Com `api` de pé (`entrypoint.sh` já migrou), os dois tenants de
desenvolvimento nascem com:

```
docker compose run --rm api python manage.py semear
```

Recria do zero — **apaga** o que estiver nas oito tabelas de tenant antes de
inserir de novo (`TRUNCATE ... RESTART IDENTITY CASCADE`, pela conexão
`owner`). Só roda com `DJANGO_DEBUG=1` (o padrão do `api` neste compose): a
senha que ele planta em toda conta de barbeiro é a conhecida `123456`, e a
trava existe para um `semear` distraído não fazer isso em produção. Ao final:
Téo (`11911112222`), Rael (`11933334444`) e Tony (`11977778888`, na Dom Tony)
entram com `123456`; Duda (`11955556666`) nasce **sem** senha de propósito —
é o convite pendente.

Duas saídas de emergência, portadas de scripts que o front tinha antes da
fatia 8 e que hoje só existem aqui:

- **Credencial do admin da plataforma.** Sem `ADMIN_USUARIO`/
  `ADMIN_SENHA_HASH_B64` no `.env`, o login do admin apenas nega. Gerar o
  hash:

  ```
  docker compose run --rm api python manage.py admin_hash "uma senha longa"
  ```

  Colar a saída (já em `ADMIN_SENHA_HASH_B64="..."`) no `.env`, ao lado de um
  `ADMIN_USUARIO` escolhido à mão.

- **Senha ou trava de um barbeiro, direto pelo banco.** Reemitir convite
  apaga a senha (`senha_hash` volta a nulo — é o reset de senha do produto), e
  o token do convite só existe em hash: link perdido não tem volta pela tela.
  Se isso acontecer com o último dono ativo, a barbearia fica sem ninguém que
  entre — daí este comando não passar por sessão nem por tela:

  ```
  docker compose run --rm api python manage.py barbeiro_senha 11911112222 "uma senha longa"
  docker compose run --rm api python manage.py barbeiro_senha 11911112222 --destravar
  ```

  A primeira forma troca a senha (mínimo de `SENHA_MINIMA` caracteres) e
  derruba as sessões antigas daquela pessoa; a segunda só zera tentativas e
  bloqueio, sem tocar na senha. As duas aceitam o WhatsApp com ou sem
  formatação.

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

### Sem pré-requisito: `brutus_test` migra sozinho

`docker/init-db.sql` já cria `brutus_test` junto com `brutus`, de propriedade
de `brutus_owner`, no mesmo volume. A fixture de sessão `django_db_setup`
(`tests/conftest.py`) chama `manage.py migrate --database=owner` antes do
primeiro teste que toca banco — a mesma migração que `entrypoint.sh` roda ao
subir o `api`, só que contra `brutus_test`. A primeira corrida já cria as
tabelas; não há passo manual, e não há nada a rodar no `front`.

`migrate` é idempotente — numa segunda corrida ele lê `django_migrations`, não
acha nada a aplicar e sai. O que ele **não** faz é reconciliar um schema que
mudou: depois de alterar um model, o banco de teste precisa ser derrubado e
recriado (`docker compose down -v` na raiz deste repo) para a migration
recomeçar do zero.

## Quem migra este banco

**Este repositório é quem cria e migra tabela em `brutus` e em `brutus_test`.**
Foi o Prisma, do lado do `front`, até a fatia 1 — a inversão de dono é mais
antiga que a saída do Prisma do front (fatia 8), que só apagou o que já tinha
ficado redundante do lado de lá. Isso está refletido em três lugares que não
devem divergir entre si:

- `entrypoint.sh` roda `manage.py migrate --noinput --database=owner` antes de
  subir o `api` — `--database=owner`, e não a conexão default, porque é
  `brutus_owner` quem tem DDL (`brutus_app`, o papel do runtime, não tem, e
  nem deve ter).
- `backend/tenant/migrations/` tem a migração de cada mudança de schema (hoje
  quatro: `0001_inicial`, a criação das tabelas; `0002_rls`, a política de RLS;
  `0003_restricoes`, os `EXCLUDE`; `0004_admin_grants`, os `GRANT` do papel
  `brutus_admin`). `tenant/models.py` não é mais `managed = False` — os models
  são a fonte da verdade do schema agora, não um espelho de outra ferramenta.
- `pytest.ini` roda **sem** `--no-migrations` de propósito: são as migrations
  que criam o schema, o RLS, o `EXCLUDE` e os `GRANT`s, e pular todas testaria
  um banco que nenhum ambiente real tem — sem política de RLS, `test_rls.py`
  provaria isolamento que não existe.

`INSTALLED_APPS` (`backend/backend/settings.py`) continua deliberadamente
mínimo — sem `contrib.admin`, `contrib.auth`, `contrib.contenttypes`,
`sessions` nem `django_celery_beat` — mas não porque outra ferramenta seja
dona do schema: é porque nenhum dos cinco tem uso aqui, e cada um criaria
tabela própria (`django_content_type`, `django_session`, a agenda em tabela do
beat, ...) sem consumidor nenhum do lado da API. `makemigrations` contra um
model novo de `tenant` é o caminho normal agora — o que continua sem lugar
aqui é um app do Django trazendo schema que este projeto não pediu.
