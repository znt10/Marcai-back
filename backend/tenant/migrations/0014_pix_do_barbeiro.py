from django.db import migrations, models

# `cidade` em `tenant_barbearia` NAO ganha GRANT para `brutus_app`: so' o admin
# da plataforma a preenche (alias `admin`, que ja tem UPDATE na tabela toda).
# As colunas do barbeiro dispensam GRANT: `tenant_barbeiro` esta sob RLS e o
# runtime ja tem UPDATE na tabela inteira.


class Migration(migrations.Migration):
    dependencies = [("tenant", "0013_mensalidade")]

    operations = [
        migrations.AddField(
            model_name="barbearia",
            name="cidade",
            field=models.TextField(default="", blank=True),
        ),
        migrations.AddField(
            model_name="barbeiro",
            name="cobra_no_agendamento",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="barbeiro",
            name="pix_chave",
            field=models.TextField(default="", blank=True),
        ),
        migrations.AddField(
            model_name="barbeiro",
            name="pix_titular",
            field=models.TextField(default="", blank=True),
        ),
    ]
