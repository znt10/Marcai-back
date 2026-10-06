import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Tabela de tenant NOVA: nasce com politica e GRANT aqui, na propria
# migration, como a 0005 e a 0006 fizeram.
_T = "tenant_listadodiaenviada"

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


def _todas_com_zap(apps, schema_editor):
    """Etapa 1 do numero central (spec 2026-10-06): toda barbearia passa a
    mandar WhatsApp ao cliente, pelo central. Voltar nao desfaz: nao ha como
    saber quem era sem zap antes."""
    Barbearia = apps.get_model("tenant", "Barbearia")
    Barbearia.objects.using(schema_editor.connection.alias).update(plano="COM_ZAP")


class Migration(migrations.Migration):
    dependencies = [("tenant", "0006_bot_agendamento")]

    operations = [
        migrations.AlterField(
            model_name="barbearia",
            name="plano",
            field=models.CharField(
                choices=[("SEM_ZAP", "Sem Zap"), ("COM_ZAP", "Com Zap")],
                default="COM_ZAP",
                max_length=20,
            ),
        ),
        migrations.RunPython(_todas_com_zap, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ListaDoDiaEnviada",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("dia", models.DateField()),
                ("mensagem_id", models.TextField()),
                ("remote_jid", models.TextField()),
                ("enviada_em", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "barbearia",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="listas_enviadas",
                        to="tenant.barbearia",
                    ),
                ),
                (
                    "barbeiro",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="listas_enviadas",
                        to="tenant.barbeiro",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("barbeiro", "dia"), name="lista_por_barbeiro_e_dia",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
