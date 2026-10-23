import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Tabela de tenant NOVA: nasce com politica e GRANT aqui, como a 0006.
_T = "tenant_custo"

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
    dependencies = [("tenant", "0013_conta_do_cliente")]

    operations = [
        migrations.CreateModel(
            name="Custo",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("nome", models.TextField(blank=True, null=True)),
                ("valor_centavos", models.IntegerField()),
                ("criado_em", models.DateTimeField(default=django.utils.timezone.now)),
                ("barbearia", models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="custos", to="tenant.barbearia")),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(("valor_centavos__gt", 0)), name="custo_valor_positivo")],
            },
        ),
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
