from django.db import migrations, models

# Sem GRANT novo: so' o `brutus_admin` escreve estas duas (o admin da
# plataforma), e o GRANT de tabela da 0004 vale para coluna nova. O
# `brutus_app` so' le — o dono nao troca o ramo nem as cores.


class Migration(migrations.Migration):
    dependencies = [("tenant", "0009_hora_da_lista")]

    operations = [
        migrations.AddField(
            model_name="barbearia",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("BARBEARIA", "Barbearia"),
                    ("SOBRANCELHA", "Sobrancelha"),
                    ("OUTRO", "Outro"),
                ],
                default="BARBEARIA",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="barbearia",
            name="paleta",
            field=models.CharField(
                choices=[
                    ("PRETO_AMARELO", "Preto e amarelo"),
                    ("BRANCO_ROSE", "Branco e rosé"),
                    ("PRETO_ROSE", "Preto e rosé"),
                    ("BRANCO_DOURADO", "Branco e dourado"),
                ],
                default="PRETO_AMARELO",
                max_length=20,
            ),
        ),
    ]
