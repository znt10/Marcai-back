# Marcai — back

O backend Django do Marcai: a API que atende `<slug>.<DOMINIO_BASE>` (uma
barbearia por subdomínio), as tarefas assíncronas (Celery `worker`/`beat`) e o
serviço de WhatsApp (Evolution API).

Roda em processo separado do front (Next.js, em
**[Marcai-front](https://github.com/znt10/Marcai-front)**) e fala com o mesmo
Postgres — e **é quem cria e migra o schema** desse banco. Veja "Quem migra
este banco", no fim, antes de propor `makemigrations` ou um app novo em
`INSTALLED_APPS`.

Este repositório sobe, testa e vai para produção **sozinho**, sem o front ao
lado. As instruções abaixo foram testadas literalmente aqui — se algum comando
não funcionar mais, conserte o comando, não a memória de quem lê.

## Stack

- **Django** servindo a API, com isolamento de tenant por **Row Level Security**
  do Postgres
- **Celery** (`worker` + `beat`) para lembretes, healthcheck do WhatsApp e poda
  de histórico
- **Postgres** com dois papéis: `brutus_owner` (DDL) e `brutus_app` (runtime,
  sem DDL de propósito)
- **Redis** como broker
- **Evolution API** para o WhatsApp
- **pytest** para os testes, rodando contra um banco real com as migrações
  aplicadas

## Rede

Os dois `docker-compose.yml` (deste repositório e o do front) declaram a rede
`brutus` como `external: true` de propósito: ela é criada à mão e vive mais que
qualquer um dos dois composes, porque os containers compartilhados (Postgres,
Redis, Evolution) atendem os dois lados. Se um compose criasse a rede, ela
morreria no `down` de quem a criou e o outro lado perderia o banco no meio do
trabalho.

Antes de subir qualquer coisa, uma vez por máquina:

```bash
docker network create brutus
```

(Erro "network with name brutus already exists" na segunda vez em diante é
esperado e inofensivo.)

## Variáveis de ambiente

```bash
cp .env.example .env
```

O `.env.example` documenta cada variável. Três detalhes que costumam morder:

- **`PGDATABASE`, `PGHOST`, `PGPORT` não alimentam o `docker-compose.yml`.** Lá
  `api`, `worker` e `beat` já têm `PGHOST=db`/`PGPORT=5432` escritos direto no
  `environment:` de cada serviço. As três existem para rodar `manage.py` no
  host, fora de container, contra a porta publicada (5433). `pytest` também não
  as lê: define as suas próprias (`brutus_test`, ver `pytest.ini`).
- **`SESSAO_JWT_SECRET` e `ADMIN_JWT_SECRET` precisam ser idênticos aos do
  front**, e diferentes entre si. O cookie do barbeiro é emitido de um lado e
  lido do outro; e serem diferentes entre si é o que faz um cookie de admin não
  abrir o painel do barbeiro, sem nenhuma checagem escrita para esse fim.
- **`ADMIN_SENHA_HASH_B64` vai em base64.** Em claro o hash é
  `$argon2id$v=19$m=...`, e tanto o Compose quanto o dotenv expandem `$argon2id`
  e `$v` como variável — o valor chegaria truncado ao processo, a senha nunca
  conferiria, e o sintoma seria um "usuário ou senha inválidos" que não explica
  nada.

## Subir

```bash
docker compose up -d --build
```

Sobe `db` (Postgres, publicado em `localhost:5433`), `redis`, `evolution`
(WhatsApp), `api` (Django em `localhost:8000`), `worker` e `beat`. Confira o
estado com `docker compose ps`.

Se um `docker compose run` ou `up` **travar em silêncio** em vez de dar erro, o
sintoma de sempre é o `db` tendo saído sozinho antes — confira
`docker compose ps` primeiro; se `db` não estiver `healthy`, é por aí.

## Popular o banco (dev)

Com `api` de pé (o `entrypoint.sh` já migrou):

```bash
docker compose run --rm api python manage.py semear
```

Recria do zero — **apaga** o que estiver nas oito tabelas de tenant antes de
inserir de novo (`TRUNCATE ... RESTART IDENTITY CASCADE`, pela conexão
`owner`). Só roda com `DJANGO_DEBUG=1`: a senha que ele planta em toda conta de
barbeiro é conhecida, e a trava existe para um `semear` distraído não fazer
isso em produção.

Ao final nascem duas barbearias com equipe, e uma das contas nasce **sem**
senha de propósito — é o convite pendente.

## Duas saídas de emergência

**Credencial do admin da plataforma.** Sem `ADMIN_USUARIO` /
`ADMIN_SENHA_HASH_B64` no `.env`, o login do admin apenas nega. Para gerar o
hash:

```bash
docker compose run --rm api python manage.py admin_hash "uma senha longa"
```

Cole a saída (já no formato `ADMIN_SENHA_HASH_B64="..."`) no `.env`, ao lado de
um `ADMIN_USUARIO` escolhido à mão.

**Senha ou trava de um barbeiro, direto pelo banco.** Reemitir convite apaga a
senha (`senha_hash` volta a nulo — é o reset de senha do produto), e o token do
convite só existe em hash: link perdido não tem volta pela tela. Se isso
acontecer com o último dono ativo, a barbearia fica sem ninguém que entre — daí
este comando não passar por sessão nem por tela:

```bash
docker compose run --rm api python manage.py barbeiro_senha 11911112222 "uma senha longa"
docker compose run --rm api python manage.py barbeiro_senha 11911112222 --destravar
```

A primeira forma troca a senha (mínimo de `SENHA_MINIMA` caracteres) e derruba
as sessões antigas daquela pessoa; a segunda só zera tentativas e bloqueio, sem
tocar na senha. As duas aceitam o WhatsApp com ou sem formatação.

## Rodar os testes

### Em Docker (preferida, não precisa de venv)

```bash
docker compose run --rm api pytest -q
```

Roda o `api` já com `PGHOST=db`/`PGPORT=5432` contra o `brutus_test` do próprio
Postgres do compose.

### No host

Com o virtualenv ativo e o compose no ar:

```bash
python -m pytest -v
```

Neste modo o `pytest.ini` aponta para `localhost:5433` (a porta publicada do
`db`) por padrão — não é preciso exportar nada além de já ter feito
`docker compose up`.

### Sem pré-requisito: `brutus_test` migra sozinho

`docker/init-db.sql` cria `brutus_test` junto com `brutus`, de propriedade de
`brutus_owner`, no mesmo volume. A fixture de sessão `django_db_setup`
(`tests/conftest.py`) chama `manage.py migrate --database=owner` antes do
primeiro teste que toca banco — a mesma migração que o `entrypoint.sh` roda ao
subir o `api`, só que contra `brutus_test`. A primeira corrida já cria as
tabelas; não há passo manual.

`migrate` é idempotente. O que ele **não** faz é reconciliar um schema que
mudou: depois de alterar um model, o banco de teste precisa ser derrubado e
recriado (`docker compose down -v`) para a migração recomeçar do zero.

## Quem migra este banco

**Este repositório é quem cria e migra tabela em `brutus` e em `brutus_test`.**
Isso está refletido em três lugares que não devem divergir entre si:

- `entrypoint.sh` roda `manage.py migrate --noinput --database=owner` antes de
  subir o `api` — `--database=owner`, e não a conexão default, porque é
  `brutus_owner` quem tem DDL (`brutus_app`, o papel do runtime, não tem, e nem
  deve ter).
- `backend/tenant/migrations/` tem a migração de cada mudança de schema:
  `0001_inicial` (as tabelas), `0002_rls` (a política de RLS), `0003_restricoes`
  (os `EXCLUDE`) e `0004_admin_grants` (os `GRANT` do papel `brutus_admin`).
  `tenant/models.py` é a fonte da verdade do schema.
- `pytest.ini` roda **sem** `--no-migrations` de propósito: são as migrações que
  criam o schema, o RLS, o `EXCLUDE` e os `GRANT`s, e pular todas testaria um
  banco que nenhum ambiente real tem — sem política de RLS, `test_rls.py`
  provaria isolamento que não existe.

`INSTALLED_APPS` (`backend/backend/settings.py`) é deliberadamente mínimo — sem
`contrib.admin`, `contrib.auth`, `contrib.contenttypes`, `sessions` nem
`django_celery_beat`: nenhum dos cinco tem uso aqui, e cada um criaria tabela
própria (`django_content_type`, `django_session`, a agenda em tabela do beat, …)
sem consumidor nenhum do lado da API. `makemigrations` contra um model novo de
`tenant` é o caminho normal; o que não tem lugar aqui é um app do Django
trazendo schema que este projeto não pediu.

## Licença

MIT — veja o arquivo [`LICENSE`](LICENSE).
