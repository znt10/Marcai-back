import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# As duas tabelas de tenant NOVAS. Elas nascem com politica e GRANT AQUI, na
# propria migration delas, e nao numa edicao da 0002/0004 — que e exatamente o
# que o comentario da 0004 mandou fazer no dia em que entrasse uma tabela de
# tenant nova. Migration aplicada e historia congelada.
#
# `tenant_barbearia` continua de fora, e continua pelo mesmo motivo de sempre:
# ela e lida ANTES de existir tenant. A coluna `plano` que esta migration
# acrescenta a ela nao muda nada nisso — quem a protege segue sendo o REVOKE da
# 0002 (`brutus_app` sem UPDATE) mais o GRANT da 0004 (`brutus_admin` com
# INSERT/UPDATE na tabela inteira, plano incluso). Nenhuma linha nova de
# permissao e' precisa para o plano; a unica coisa que seria um erro e' abrir
# UPDATE de `plano` para `brutus_app`, e e' justamente para nao precisar disso
# que o estado da conexao mora em `tenant_whatsappinstancia`.
TABELAS = [
    "tenant_whatsappinstancia",
    "tenant_mensagemnaoenviada",
]

CRIAR = []
REMOVER = []

for _t in TABELAS:
    CRIAR += [
        f"ALTER TABLE {_t} ENABLE ROW LEVEL SECURITY;",
        # FORCE aplica a politica ate ao DONO da tabela, como nas outras sete.
        f"ALTER TABLE {_t} FORCE  ROW LEVEL SECURITY;",
        # Ja nasce nomeando os DOIS papeis de runtime. Na 0002 a politica
        # nasceu so' com `brutus_app` e a 0004 teve que corrigir com um ALTER;
        # nao ha por que repetir aqui o erro para em seguida corrigi-lo.
        #
        # O `::text` no lado ESQUERDO pelo mesmo motivo da 0002: a coluna e
        # `uuid`, `current_setting` devolve `text`, e um cast do lado direito
        # estouraria com erro de sintaxe se a variavel viesse com lixo, em vez
        # de simplesmente nao casar com linha nenhuma. Falha fechada.
        f"""
        CREATE POLICY tenant_isolation ON {_t}
            TO brutus_app, brutus_admin
            USING      (barbearia_id::text = current_setting('app.barbearia_id', true))
            WITH CHECK (barbearia_id::text = current_setting('app.barbearia_id', true));
        """,
        # Contrapeso ao FORCE: migration, seed e montagem de cenario de teste
        # rodam como `brutus_owner` e atravessam varios tenants na mesma
        # conexao.
        f"""
        CREATE POLICY owner_irrestrito ON {_t}
            TO brutus_owner
            USING (true) WITH CHECK (true);
        """,
        # O `ALTER DEFAULT PRIVILEGES` do init-db.sh ja concede DML nas tabelas
        # que `brutus_owner` cria depois dele, entao estas duas linhas sao rede,
        # e nao o caminho principal — a mesma rede que a 0004 armou para as
        # outras oito. GRANT e idempotente; faltar custaria "permission denied"
        # no primeiro webhook, num banco montado antes daquele ALTER.
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_t} TO brutus_app;",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_t} TO brutus_admin;",
    ]
    REMOVER += [
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_t} FROM brutus_admin;",
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_t} FROM brutus_app;",
        f"DROP POLICY IF EXISTS owner_irrestrito ON {_t};",
        f"DROP POLICY IF EXISTS tenant_isolation ON {_t};",
        f"ALTER TABLE {_t} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {_t} DISABLE ROW LEVEL SECURITY;",
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("tenant", "0004_admin_grants"),
    ]

    operations = [
        migrations.AddField(
            model_name="barbearia",
            name="plano",
            field=models.CharField(
                choices=[("SEM_ZAP", "Sem Zap"), ("COM_ZAP", "Com Zap")],
                default="SEM_ZAP",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="MensagemNaoEnviada",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                (
                    "tipo",
                    models.CharField(
                        choices=[
                            ("CONFIRMACAO", "Confirmacao"),
                            ("CANCELAMENTO", "Cancelamento"),
                            ("LEMBRETE", "Lembrete"),
                        ],
                        max_length=20,
                    ),
                ),
                ("cliente_nome", models.TextField()),
                ("criado_em", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "barbearia",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="nao_enviadas",
                        to="tenant.barbearia",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="WhatsappInstancia",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("nome", models.TextField(unique=True)),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("PENDENTE", "Pendente"),
                            ("AGUARDANDO_QR", "Aguardando Qr"),
                            ("CONECTADO", "Conectado"),
                            ("DESCONECTADO", "Desconectado"),
                        ],
                        default="PENDENTE",
                        max_length=20,
                    ),
                ),
                ("qr_base64", models.TextField(null=True)),
                ("numero_conectado", models.TextField(null=True)),
                ("desconectado_desde", models.DateTimeField(null=True)),
                ("atualizado_em", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "barbearia",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="whatsapp",
                        to="tenant.barbearia",
                    ),
                ),
            ],
        ),
        # Depois do CreateModel, obrigatoriamente: as politicas falam de tabelas
        # que so existem a partir das operacoes acima.
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
