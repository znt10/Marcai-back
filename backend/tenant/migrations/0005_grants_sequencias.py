from django.db import migrations

# As tabelas contrib que a etapa do admin faz nascer (auth_user, auth_group,
# auth_permission, django_content_type, django_admin_log, e as tabelas de
# ligacao) usam `id serial`/`bigserial` — cada uma delas e' coluna MAIS
# sequencia. O `ALTER DEFAULT PRIVILEGES ... GRANT ... ON TABLES` que ja existe
# (init-db.sql e a 0004) cobre so' a tabela: SEQUENCES e' uma categoria
# separada pro Postgres, e fica de fora. Sem o GRANT aqui, `brutus_app`
# consegue fazer INSERT na tabela mas nao consegue tirar o proximo valor do
# serial — confirmado num probe manual (CREATE TABLE com serial como
# brutus_owner, INSERT como brutus_app: "permission denied for sequence").
# Na pratica isso quebra `createsuperuser`, a criacao de usuario em teste, e
# qualquer escrita do admin (que grava em django_admin_log a cada save).
#
# Os dois comandos abaixo sao os dois necessarios, nao um so': a ordem entre a
# migration do `tenant` e as migrations dos apps contrib (auth, admin, ...) no
# grafo de dependencias do Django NAO e' garantida. Se esta migration rodar
# ANTES das tabelas contrib nascerem, `ON ALL SEQUENCES IN SCHEMA public` so'
# pega o que ja existe no momento do comando — nada delas — e quem cobre e' o
# `ALTER DEFAULT PRIVILEGES`, que vale para o que `brutus_owner` criar DEPOIS.
# Se rodar DEPOIS, e' o primeiro comando que ja cobre tudo. Um so' dos dois
# comandos nao cobre os dois casos possiveis de ordem.
GRANTS = [
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO brutus_app, brutus_admin;",
    "ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public "
    "GRANT USAGE, SELECT ON SEQUENCES TO brutus_app, brutus_admin;",
]

REVOGAR = [
    "ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner IN SCHEMA public "
    "REVOKE USAGE, SELECT ON SEQUENCES FROM brutus_app, brutus_admin;",
    "REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM brutus_app, brutus_admin;",
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0004_admin_grants")]

    operations = [migrations.RunSQL(sql=GRANTS, reverse_sql=REVOGAR)]
