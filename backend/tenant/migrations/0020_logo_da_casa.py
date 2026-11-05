from django.db import migrations, models

# O dono sobe a logo pelo painel, que roda como `brutus_app` — sem UPDATE em
# `tenant_barbearia` desde o REVOKE da 0002. Por COLUNA, como a 0009 fez com
# `hora_da_lista_min`: slug, ativo, plano, tipo e paleta seguem fora do
# alcance do runtime.
CRIAR = ["GRANT UPDATE (logo_url) ON tenant_barbearia TO brutus_app;"]
REMOVER = ["REVOKE UPDATE (logo_url) ON tenant_barbearia FROM brutus_app;"]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0019_cabeleireira_e_rose")]

    operations = [
        migrations.AddField(
            model_name="barbearia",
            name="logo_url",
            field=models.TextField(null=True),
        ),
        migrations.RunSQL(CRIAR, REMOVER),
    ]
