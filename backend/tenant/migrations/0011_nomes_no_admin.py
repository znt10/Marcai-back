from django.db import migrations

# So' o nome que o admin do Django mostra; nao toca no banco.


class Migration(migrations.Migration):
    dependencies = [("tenant", "0010_tipo_e_paleta")]

    operations = [
        migrations.AlterModelOptions(
            name="barbearia",
            options={"verbose_name": "estabelecimento", "verbose_name_plural": "estabelecimentos"},
        ),
        migrations.AlterModelOptions(
            name="barbeiro",
            options={"verbose_name": "profissional", "verbose_name_plural": "profissionais"},
        ),
    ]
