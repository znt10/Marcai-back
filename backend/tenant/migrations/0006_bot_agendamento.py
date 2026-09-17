import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Tabela de tenant NOVA: nasce com politica e GRANT aqui, na propria migration,
# como a 0005 fez — migration aplicada e' historia congelada.
_T = "tenant_conversawhatsapp"

CRIAR = [
    f"ALTER TABLE {_T} ENABLE ROW LEVEL SECURITY;",
    f"ALTER TABLE {_T} FORCE  ROW LEVEL SECURITY;",
    f"""
    CREATE POLICY tenant_isolation ON {_T}
        TO brutus_app, brutus_admin
        USING      (barbearia_id::text = current_setting('app.barbearia_id', true))
        WITH CHECK (barbearia_id::text = current_setting('app.barbearia_id', true));
    """,
    f"""
    CREATE POLICY owner_irrestrito ON {_T}
        TO brutus_owner
        USING (true) WITH CHECK (true);
    """,
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_T} TO brutus_app;",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_T} TO brutus_admin;",
]

REMOVER = [
    f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_T} FROM brutus_admin;",
    f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_T} FROM brutus_app;",
    f"DROP POLICY IF EXISTS owner_irrestrito ON {_T};",
    f"DROP POLICY IF EXISTS tenant_isolation ON {_T};",
    f"ALTER TABLE {_T} NO FORCE ROW LEVEL SECURITY;",
    f"ALTER TABLE {_T} DISABLE ROW LEVEL SECURITY;",
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0005_whatsapp_por_barbearia")]

    operations = [
        migrations.AddField(
            model_name="whatsappinstancia",
            name="bot_ativo",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="ConversaWhatsapp",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("whatsapp", models.TextField()),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("MENU", "Menu"),
                            ("SERVICO", "Servico"),
                            ("BARBEIRO", "Barbeiro"),
                            ("DIA", "Dia"),
                            ("HORA", "Hora"),
                            ("NOME", "Nome"),
                            ("CONFIRMA", "Confirma"),
                            ("QUAL_AGENDAMENTO", "Qual Agendamento"),
                            ("CONFIRMA_CANCEL", "Confirma Cancel"),
                            ("AGUARDANDO_LEMBRETE", "Aguardando Lembrete"),
                        ],
                        default="MENU",
                        max_length=24,
                    ),
                ),
                ("opcoes", models.JSONField(default=list)),
                ("rascunho", models.JSONField(default=dict)),
                ("tentativas", models.IntegerField(default=0)),
                ("pergunta", models.TextField(null=True)),
                ("ultima_mensagem_id", models.TextField(null=True)),
                ("ids_do_bot", models.JSONField(default=list)),
                ("mudo_ate", models.DateTimeField(null=True)),
                ("atualizado_em", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "barbearia",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="conversas",
                        to="tenant.barbearia",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("barbearia", "whatsapp"), name="conversa_por_numero",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
