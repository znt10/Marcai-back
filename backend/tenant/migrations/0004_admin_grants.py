from django.db import migrations

# As mesmas sete da 0002. Repetidas, e nao importadas de la, porque o nome
# `0002_rls` comeca com digito e nao e um identificador Python valido — o
# import so sairia via importlib, o que trocaria uma lista de sete strings por
# um truque. Migration aplicada e historia congelada: se um dia entrar uma
# tabela de tenant nova, ela nasce com politica na PROPRIA migration dela, e
# nenhuma destas duas listas muda.
TABELAS = [
    "tenant_barbeiro",
    "tenant_servico",
    "tenant_barbeiroservico",
    "tenant_horariotrabalho",
    "tenant_bloqueio",
    "tenant_cliente",
    "tenant_agendamento",
]

# Porte das migrations `20260806170000_admin_grants` e `20260806173000_admin_rls`
# do Prisma, juntas: separadas la porque a segunda foi a correcao da primeira,
# e nao ha por que reproduzir o erro para em seguida corrigi-lo.
CRIAR = [
    # O `docker/init-db.sql` ja cria o papel num volume novo. O CREATE
    # idempotente aqui cobre banco que nasceu antes desta etapa — e o motivo de
    # `brutus_owner` ter CREATEROLE.
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brutus_admin') THEN
        CREATE ROLE brutus_admin LOGIN PASSWORD 'admin';
      END IF;
    END $$;
    """,
    "GRANT USAGE ON SCHEMA public TO brutus_admin;",
]

# DML nas tabelas de tenant. O `ALTER DEFAULT PRIVILEGES` do init-db.sql ja
# cobre tudo que `brutus_owner` cria depois dele — e agora quem cria e o
# Django, entao as oito tabelas ja nascem com o GRANT. Isto aqui e a rede para
# um banco que ja existia antes: GRANT e idempotente, repetir nao custa nada,
# e faltar custaria "permission denied" no primeiro pedido do admin.
#
# Nomeadas uma a uma em vez de `ON ALL TABLES IN SCHEMA public` (como o Prisma
# fazia) porque o schema deixou de ser so' as tabelas do dominio: `ON ALL
# TABLES` hoje entregaria tambem INSERT/UPDATE/DELETE em `django_migrations`,
# que e o historico de quem e' dono do schema. Um papel de runtime nao tem o
# que fazer ali.
CRIAR += [
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO brutus_admin;"
    for t in TABELAS + ["tenant_barbearia"]
]

CRIAR += [
    # A UNICA capacidade que o brutus_app nao tem. E' esta linha que distingue
    # os dois papeis; todo o resto e igual. A 0002 fez o
    # `REVOKE INSERT, UPDATE, DELETE ON tenant_barbearia FROM brutus_app` e isso
    # continua valendo — o teste de papel do admin confere.
    "GRANT INSERT, UPDATE ON tenant_barbearia TO brutus_admin;",
]

# As politicas nasceram com `TO brutus_app`. Com RLS ligado, um papel que nao
# casa com politica nenhuma nao enxerga linha nenhuma — falha fechada, que e a
# propriedade certa, mas deixaria o brutus_admin cego inclusive dentro de
# `com_barbearia_admin()`.
#
# A correcao e NOMEAR o admin na MESMA politica, e nao criar uma paralela: a
# regra de isolamento continua escrita num lugar so. Se um dia ela mudar, muda
# para os dois papeis de uma vez.
#
# Nada de BYPASSRLS, de proposito: fora de `com_barbearia_admin()` o admin da
# plataforma nao enxerga linha de tenant nenhuma, igual ao runtime.
CRIAR += [
    f"ALTER POLICY tenant_isolation ON {t} TO brutus_app, brutus_admin;"
    for t in TABELAS
]

REMOVER = [
    f"ALTER POLICY tenant_isolation ON {t} TO brutus_app;" for t in TABELAS
] + [
    "REVOKE INSERT, UPDATE ON tenant_barbearia FROM brutus_admin;",
] + [
    f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {t} FROM brutus_admin;"
    for t in TABELAS + ["tenant_barbearia"]
] + [
    "REVOKE USAGE ON SCHEMA public FROM brutus_admin;",
    # O papel NAO e derrubado no reverso: ele e criado pelo init-db.sql antes
    # de qualquer migration rodar, e um DROP ROLE aqui apagaria uma coisa que
    # esta migration nao criou. Reverter tem que devolver o banco ao estado
    # anterior, nao a um estado que nunca existiu.
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0003_restricoes")]

    operations = [migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER)]
