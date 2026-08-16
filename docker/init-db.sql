-- Papel dono: roda migração, é dono das tabelas, IGNORA RLS.
CREATE ROLE brutus_owner LOGIN PASSWORD 'owner';

-- CREATEDB: exigido por `prisma migrate dev`, que cria um shadow database
-- temporário para calcular o diff da migração. Sem isso, `migrate dev` falha
-- com P3014. Não concede acesso a dados de outros bancos, só o direito de
-- criar/derrubar bancos (o shadow database é descartado ao final).
ALTER ROLE brutus_owner CREATEDB;

-- CREATEROLE: a migração admin_grants cria o papel brutus_admin, e migração
-- roda como este papel. Sem isso, `prisma migrate deploy` numa máquina nova
-- morre com "permission denied to create role" — e a alternativa seria
-- exigir um passo manual de superusuário antes de todo deploy.
-- Não é superusuário: não lê dado de outro banco nem ignora RLS.
ALTER ROLE brutus_owner CREATEROLE;

-- Papel da aplicação: só DML, jamais dono. É sobre ele que o RLS age.
CREATE ROLE brutus_app LOGIN PASSWORD 'app';

-- Papel do admin da plataforma: é o brutus_app MAIS a porta de entrada
-- (INSERT/UPDATE em Barbearia). Sem BYPASSRLS, de propósito — o admin
-- continua sujeito ao RLS em toda tabela de tenant.
CREATE ROLE brutus_admin LOGIN PASSWORD 'admin';

-- Papel da Evolution API. Nada a ver com os três de cima: ele é dono do
-- PRÓPRIO banco e não recebe GRANT nenhum em `brutus` — a instância de
-- WhatsApp não tem por que enxergar dado de barbearia, e o RLS não é a
-- barreira aqui, a separação de banco é.
CREATE ROLE evolution LOGIN PASSWORD 'evolution';

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
