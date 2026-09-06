# Contexto do backend

Projeto: Marcai (agendamento de barbearia)
Parte: Backend
Stack: Django 6, Django REST Framework, PostgreSQL 16 (com Row Level Security), Celery + Redis, Evolution API (WhatsApp)

**São DOIS repositórios irmãos**, lado a lado: `Marcai-back` (este) e `Marcai-front`.
Mudança que atravessa os dois precisa de commit nos dois. As specs e os planos de
implementação de **ambos** moram em `Marcai-front/docs/superpowers/`.

## Estrutura

```
backend/
├── tenant/           # Models, RLS, middleware, resolução de subdomínio
│   ├── models.py     # As 8 tabelas; Barbearia + 7 sob RLS
│   ├── rls.py        # com_barbearia() e irmãs — o ÚNICO lugar com cursor.execute
│   ├── middleware.py # Tenant, Cliente, BarreiraAdmin, CrivoPainel, AdminDjango
│   ├── datas.py      # O ÚNICO lugar que sabe de fuso horário
│   └── migrations/   # 0002_rls.py tem as políticas; 0004 os GRANTs do admin
├── app/              # A superfície
│   ├── api/v1/       # router.py, views/, serializers/ — a API JSON
│   ├── services/     # A regra de negócio (agendamentos, slots, resumo, ...)
│   ├── admin.py      # Os ModelAdmin do admin do Django
│   └── tasks.py      # Celery: lembretes, healthcheck do WhatsApp, zelador
└── backend/          # settings.py, urls.py
tests/                # pytest; conftest.py tem as fixtures `cenario` e `limpar_banco`
docker/init-db.sql    # Cria os papéis do banco e os DEFAULT PRIVILEGES
```

## O que você precisa saber antes de escrever qualquer linha

**O tenant vem do Host.** Não há `?barbearia=` nem header de tenant: o subdomínio
**é** a barbearia (`brutus.localhost`, `dontony.localhost`), e `admin.<domínio>` é o
painel da plataforma. Quem resolve é o `TenantMiddleware`, lendo o Host **real** —
nunca um header de upstream, porque o back precisa subir sozinho, sem o front na frente.

**O isolamento é do Postgres, não do Python.** Sete das oito tabelas têm Row Level
Security ligada **e forçada**, com a política
`USING (barbearia_id::text = current_setting('app.barbearia_id', true))`. Sem a
variável definida, `current_setting` devolve NULL, a comparação não é verdadeira, e
**não sai linha nenhuma**. Não escreva `.filter(barbearia_id=...)` achando que é isso
que protege — não é, e um filtro esquecido não vaza dado, ele some com tudo.

`tenant_barbearia` é a exceção: fica **fora** do RLS (é lida antes de existir tenant)
e é protegida por GRANT.

**Toda consulta a model de tenant vai dentro de `with com_barbearia(id):`.**
`tests/test_varredura.py` é uma varredura de AST que reprova o build se você esquecer,
e também se escrever qualquer `.execute(...)` em `backend/tenant/` fora de `rls.py`.
Quando ela acusar, a saída quase nunca é acrescentar o arquivo a `ISENTOS` — é
envolver a consulta no wrapper.

**`com_barbearia` usa `atomic(durable=True)`.** Aninhar dois estoura `RuntimeError`
de propósito: dentro de um bloco durable, um segundo `atomic` viraria SAVEPOINT, e
sair dele NÃO devolveria o tenant de fora — dado com cara de certo, da barbearia
errada, sem erro nenhum.

**Três papéis no banco, e nenhum tem BYPASSRLS:**
- `brutus_app` — conexão `default`, o runtime. É sobre ele que o RLS age.
- `brutus_owner` — DDL, roda as migrations, ignora RLS. Só para montar cenário de teste.
- `brutus_admin` — conexão `admin`, mesmo RLS + GRANT extra em `tenant_barbearia`.

**Fuso horário é só `tenant/datas.py`.** Nenhum outro arquivo converte data.

**As barreiras são posicionais.** `BarreiraAdminMiddleware` devolve 404 para tudo sob
`/admin` e `/api/admin` fora do host do admin — então rota nova sob esses prefixos
**nasce protegida sem decidir nada**. É 404 e não 403 de propósito: 403 confirmaria
que o recurso existe.

## Como rodar

```bash
docker compose run --rm api pytest -q            # a suíte inteira
docker compose run --rm api pytest -q tests/test_x.py
docker compose up -d                             # sobe api, db, worker, beat, redis, evolution
docker compose run --rm api python manage.py migrate --noinput --database=owner
```

Os testes rodam contra `brutus_test`, migrado pela fixture `django_db_setup` como
`owner`. Depois de mexer num model, o banco de teste precisa ser derrubado e recriado
(`docker compose down -v`) — `migrate` não reconcilia schema que mudou.

O admin do Django fica em `/admin/django/`, e exige **dois logins**: o cookie
`sessao_admin` da plataforma abre a porta, o login do Django entra. Escolha a
barbearia em `/admin/django/escolher-barbearia` — antes disso as listas vêm vazias,
e isso é o comportamento certo.

## Regras

- Comentário em **português**, explicando *por quê*, não *o quê*. Tom de referência:
  `backend/tenant/middleware.py`.
- Mensagem de commit minúscula, `área: frase em português`. Sem `feat:`/`fix:`.
- Nunca `git add -A`, `git add .` nem `git commit -a` — liste os arquivos um a um.
- TDD: escreve o teste, roda e vê falhar **pelo motivo certo**, implementa, roda e vê passar.
- Teste de banco usa `transaction=True` no marcador `django_db`.

## Antes de finalizar

- `docker compose run --rm api pytest -q` — o número **nunca** pode cair.
- `tests/test_varredura.py` passando.
- Se afirmar que alguma coisa é necessária, mostre o **controle negativo**: o estado
  sem ela, falhando. Prova rodada só com a coisa já aplicada não distingue "era
  necessário" de "era irrelevante".
- Diga quais arquivos mudaram e por quê.
