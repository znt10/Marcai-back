#!/bin/sh
# Cria os papéis e os bancos na PRIMEIRA subida do volume do Postgres.
#
# Era `init-db.sql`, com as senhas escritas no arquivo ('owner', 'app',
# 'admin', 'evolution'). Isso servia em dev e não serve num servidor: o repo é
# público, então a senha do banco de produção estaria no GitHub. Virou shell
# para ler as senhas do ambiente — com as MESMAS senhas de antes como padrão,
# para o compose de dev continuar subindo sem uma variável nova.
#
# Os nomes das variáveis são os que o `settings.py` já lê
# (`PGPASSWORD_OWNER`, `_APP`, `_ADMIN`, `_EVOLUTION`), de propósito: é o
# mesmo valor dos dois lados, e nomes iguais tornam a divergência visível.
#
# As senhas entram como variáveis do psql (`:'senha_owner'`), não coladas no
# texto do SQL: o psql as cita, e uma senha com aspas não quebra o comando
# nem vira SQL.
#
# Só roda num volume VAZIO — é a regra do `docker-entrypoint-initdb.d`. Trocar
# a senha aqui depois de o banco existir não muda nada: é `ALTER ROLE` à mão.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v senha_owner="${PGPASSWORD_OWNER:-owner}" \
  -v senha_app="${PGPASSWORD_APP:-app}" \
  -v senha_admin="${PGPASSWORD_ADMIN:-admin}" \
  -v senha_evolution="${PGPASSWORD_EVOLUTION:-evolution}" <<'SQL'
-- Papel dono: roda migração, é dono das tabelas, IGNORA RLS.
CREATE ROLE brutus_owner LOGIN PASSWORD :'senha_owner';

-- CREATEROLE: a migration 0004_admin_grants cria o papel brutus_admin, e
-- migration roda como este papel. Sem isso, `manage.py migrate` numa máquina
-- nova morre com "permission denied to create role" — e a alternativa seria
-- exigir um passo manual de superusuário antes de todo deploy.
--
-- CREATEDB saiu junto com o Prisma: ele era exigido só pelo shadow database
-- que `prisma migrate dev` criava para calcular o diff da migração. O
-- `makemigrations` do Django compara os models com o histórico em
-- `django_migrations` e não cria banco nenhum para isso.
-- Não é superusuário: não lê dado de outro banco nem ignora RLS.
ALTER ROLE brutus_owner CREATEROLE;

-- Papel da aplicação: só DML, jamais dono. É sobre ele que o RLS age.
CREATE ROLE brutus_app LOGIN PASSWORD :'senha_app';

-- Papel do admin da plataforma: é o brutus_app MAIS a porta de entrada
-- (INSERT/UPDATE em Barbearia). Sem BYPASSRLS, de propósito — o admin
-- continua sujeito ao RLS em toda tabela de tenant.
--
-- Criado AQUI, e não só pela migration 0004: ela o cria com a senha 'admin'
-- escrita, mas só quando o papel ainda não existe. Nascendo aqui, a senha
-- que vale é a do ambiente.
CREATE ROLE brutus_admin LOGIN PASSWORD :'senha_admin';

-- Papel da Evolution API. Nada a ver com os três de cima: ele é dono do
-- PRÓPRIO banco e não recebe GRANT nenhum em `brutus` — a instância de
-- WhatsApp não tem por que enxergar dado de barbearia, e o RLS não é a
-- barreira aqui, a separação de banco é.
CREATE ROLE evolution LOGIN PASSWORD :'senha_evolution';

CREATE DATABASE brutus      OWNER brutus_owner;
CREATE DATABASE brutus_test OWNER brutus_owner;

-- A Evolution roda as próprias migrações ao subir, então precisa ser dona do
-- banco dela.
CREATE DATABASE evolution   OWNER evolution;

-- Espelha brutus/brutus_test (mesmo motivo, card "Bancos de teste separados
-- por repositório"): sem um banco de teste PRÓPRIO, a suíte do zelador leria
-- e apagaria dado de uma instância de Evolution rodando de verdade. A
-- Evolution nunca fala com este banco — só a suíte de teste do Django, via
-- `DATABASES["evolution"]` com `PGDATABASE_EVOLUTION=evolution_test`.
CREATE DATABASE evolution_test OWNER evolution;

\connect brutus
GRANT USAGE ON SCHEMA public TO brutus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO brutus_app;
GRANT USAGE ON SCHEMA public TO brutus_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO brutus_admin;

\connect brutus_test
GRANT USAGE ON SCHEMA public TO brutus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO brutus_app;
GRANT USAGE ON SCHEMA public TO brutus_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO brutus_admin;
SQL
