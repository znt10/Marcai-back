from django.db import migrations

# As sete tabelas de tenant. `tenant_barbearia` fica de fora de proposito: ela
# e lida ANTES de existir tenant (para traduzir subdominio em id), entao nao ha
# `app.barbearia_id` a comparar quando ela e consultada. Quem a protege e o
# GRANT logo abaixo, nao politica.
TABELAS = [
    "tenant_barbeiro",
    "tenant_servico",
    "tenant_barbeiroservico",
    "tenant_horariotrabalho",
    "tenant_bloqueio",
    "tenant_cliente",
    "tenant_agendamento",
]

# Porte da migration `20260805221500_rls` do Prisma, mais o GRANT por coluna da
# `20260807120000_frase_do_horario`.
#
# A UNICA divergencia de conteudo e o `::text` na comparacao, e ela e forcada
# pela troca de tipo do `id` (ver tenant/models.py): a coluna `barbearia_id`
# agora e `uuid` e `current_setting` devolve `text`, e `uuid = text` nao
# resolve — o sintoma seria a politica ERRAR, nao recusar, porque um operador
# que nao existe vira erro de consulta em toda leitura de tenant.
#
# O lado esquerdo e' que ganha o cast, e nao o direito (`current_setting(...)
# ::uuid`), porque o valor da variavel vem de fora: um `app.barbearia_id` com
# lixo dentro faria `::uuid` estourar com erro de sintaxe no meio da consulta,
# enquanto `barbearia_id::text = 'lixo'` simplesmente nao casa com linha
# nenhuma. Falha fechada continua sendo falha fechada.
#
# `current_setting(..., true)` devolve NULL quando ninguem chamou set_config, e
# `algo = NULL` e NULL, nao verdadeiro: fora de `com_barbearia()` o runtime
# enxerga ZERO linha. E' essa a propriedade que o test_rls.py cobra.
CRIAR = [
    'REVOKE INSERT, UPDATE, DELETE ON tenant_barbearia FROM brutus_app;',
    # O dono edita a frase de horario da home pela tela de servicos, e essa e a
    # UNICA coluna de `tenant_barbearia` que o runtime escreve. Por COLUNA de
    # proposito: `brutus_app` continua sem poder mexer em slug, ativo ou
    # qualquer outra coisa da tabela — quem administra barbearia e o admin.
    'GRANT UPDATE (horario_resumo) ON tenant_barbearia TO brutus_app;',
]

REMOVER = []

for _t in TABELAS:
    CRIAR += [
        f"ALTER TABLE {_t} ENABLE ROW LEVEL SECURITY;",
        # FORCE aplica a politica ate ao DONO da tabela. Sem ele, qualquer papel
        # que venha a ser dono escaparia do RLS por padrao.
        f"ALTER TABLE {_t} FORCE  ROW LEVEL SECURITY;",
        # Amarrada a `TO brutus_app`, nao a PUBLIC: um papel futuro que ganhe
        # GRANT sem ganhar politica enxerga ZERO linhas em vez de herdar esta.
        # Falha fechada por construcao. (A 0004 acrescenta `brutus_admin` a
        # ESTA politica, em vez de criar uma paralela.)
        f"""
        CREATE POLICY tenant_isolation ON {_t}
            TO brutus_app
            USING      (barbearia_id::text = current_setting('app.barbearia_id', true))
            WITH CHECK (barbearia_id::text = current_setting('app.barbearia_id', true));
        """,
        # Contrapeso ao FORCE acima. Migracao, seed e montagem de cenario de
        # teste rodam como brutus_owner e atravessam varios tenants numa mesma
        # conexao — com FORCE e sem esta politica, todo INSERT do dono morreria
        # no WITH CHECK. `TO brutus_owner` mantem brutus_app intocado:
        # politicas permissivas se somam por OR, mas so para os papeis que elas
        # nomeiam.
        f"""
        CREATE POLICY owner_irrestrito ON {_t}
            TO brutus_owner
            USING (true) WITH CHECK (true);
        """,
    ]
    REMOVER += [
        f"DROP POLICY IF EXISTS owner_irrestrito ON {_t};",
        f"DROP POLICY IF EXISTS tenant_isolation ON {_t};",
        f"ALTER TABLE {_t} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {_t} DISABLE ROW LEVEL SECURITY;",
    ]

REMOVER += [
    "REVOKE UPDATE (horario_resumo) ON tenant_barbearia FROM brutus_app;",
    "GRANT INSERT, UPDATE, DELETE ON tenant_barbearia TO brutus_app;",
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0001_inicial")]

    operations = [migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER)]
