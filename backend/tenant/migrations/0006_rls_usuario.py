from django.db import migrations

# O RLS de `tenant_usuario`. Ele e o ponto delicado da fatia 2, e a maior parte
# dele se resolve sozinha.
#
# `tenant_isolation` compara `barbearia_id` com `current_setting`, e a linha do
# ADMIN tem `barbearia_id` NULL. Em SQL, `NULL = 'algo'` nao e falso: e NULL, e
# NULL nao satisfaz a politica. Ou seja, a linha do admin da plataforma e
# NATURALMENTE invisivel para `brutus_app`, sem precisar de excecao nenhuma
# escrita em lugar nenhum. A propriedade cai fora da algebra, e nao da nossa
# disciplina — que e a unica forma de garantia que nao se perde numa refatoracao.
#
# O que PRECISA ser escrito e so' o outro lado: deixar `brutus_admin` enxergar
# exatamente essa linha, e nada alem dela.
CRIAR = [
    "ALTER TABLE tenant_usuario ENABLE ROW LEVEL SECURITY;",
    "ALTER TABLE tenant_usuario FORCE  ROW LEVEL SECURITY;",

    # Igual as outras sete tabelas de tenant, `::text` inclusive (0002_rls
    # explica por que o cast fica do lado da coluna). Nomeia os dois papeis de
    # uma vez porque a 0004 ja ensinou que criar so' com `TO brutus_app` deixa
    # o admin cego dentro de `com_barbearia_admin()`.
    """
    CREATE POLICY tenant_isolation ON tenant_usuario
        TO brutus_app, brutus_admin
        USING      (barbearia_id::text = current_setting('app.barbearia_id', true))
        WITH CHECK (barbearia_id::text = current_setting('app.barbearia_id', true));
    """,

    # A politica que o card manda escrever, e a UNICA especifica desta tabela.
    #
    # `USING (barbearia_id IS NULL)` e' o par exato da nulidade que a
    # CheckConstraint `admin_sem_barbearia_resto_com` garante: como so' o ADMIN
    # tem `barbearia_id` NULL, esta politica alcanca a linha dele e NENHUMA
    # outra. Nao ha `papel = 'ADMIN'` escrito aqui de proposito — a regra ja
    # esta no CHECK, e duplica-la criaria dois lugares para sair de sincronia.
    #
    # Politicas permissivas se somam por OR, entao `brutus_admin` passa a ver
    # "o que e' do tenant corrente" OU "a linha do admin". Nada de BYPASSRLS,
    # como no resto do schema.
    """
    CREATE POLICY admin_da_plataforma ON tenant_usuario
        TO brutus_admin
        USING (barbearia_id IS NULL) WITH CHECK (barbearia_id IS NULL);
    """,

    # Contrapeso ao FORCE, pelo mesmo motivo das outras tabelas: migracao e
    # montagem de cenario de teste rodam como owner e atravessam tenants na
    # mesma conexao.
    """
    CREATE POLICY owner_irrestrito ON tenant_usuario
        TO brutus_owner
        USING (true) WITH CHECK (true);
    """,

    # A tabela nasce de `brutus_owner`, entao o ALTER DEFAULT PRIVILEGES do
    # init-db.sql ja concede DML aos dois papeis. Repetido aqui pela mesma
    # razao da 0004: GRANT e idempotente, e faltar custaria "permission denied"
    # no primeiro login.
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_usuario TO brutus_app;",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_usuario TO brutus_admin;",
]

REMOVER = [
    "REVOKE SELECT, INSERT, UPDATE, DELETE ON tenant_usuario FROM brutus_admin;",
    "REVOKE SELECT, INSERT, UPDATE, DELETE ON tenant_usuario FROM brutus_app;",
    "DROP POLICY IF EXISTS owner_irrestrito ON tenant_usuario;",
    "DROP POLICY IF EXISTS admin_da_plataforma ON tenant_usuario;",
    "DROP POLICY IF EXISTS tenant_isolation ON tenant_usuario;",
    "ALTER TABLE tenant_usuario NO FORCE ROW LEVEL SECURITY;",
    "ALTER TABLE tenant_usuario DISABLE ROW LEVEL SECURITY;",
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0005_usuario")]

    operations = [migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER)]
