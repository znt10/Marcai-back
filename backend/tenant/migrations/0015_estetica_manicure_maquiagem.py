from django.db import migrations, models

# So' as escolhas: SOBRANCELHA continua no banco, com o nome Estetica.


class Migration(migrations.Migration):
    dependencies = [("tenant", "0014_custo")]

    operations = [
        migrations.AlterField(
            model_name="barbearia",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("BARBEARIA", "Barbearia"),
                    ("SOBRANCELHA", "Estética"),
                    ("MANICURE", "Manicure"),
                    ("MAQUIAGEM", "Maquiagem"),
                    ("OUTRO", "Outro"),
                ],
                default="BARBEARIA",
                max_length=20,
            ),
        ),
    ]
