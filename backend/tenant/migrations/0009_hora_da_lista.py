from django.db import migrations, models

# O dono escolhe a hora da lista do dia pelo painel, e o painel roda como
# `brutus_app`, que nao tem UPDATE em `tenant_barbearia` (REVOKE da 0002).
# Por COLUNA, como o `horario_resumo` da 0002: slug, ativo e plano continuam
# fora do alcance do runtime. O `brutus_admin` ja tem UPDATE na tabela toda
# (0004), e GRANT de tabela vale para coluna nova.
CRIAR = ["GRANT UPDATE (hora_da_lista_min) ON tenant_barbearia TO brutus_app;"]
REMOVER = ["REVOKE UPDATE (hora_da_lista_min) ON tenant_barbearia FROM brutus_app;"]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0008_lista_do_dia_vai_com_o_barbeiro")]

    operations = [
        migrations.AddField(
            model_name="barbearia",
            name="hora_da_lista_min",
            field=models.PositiveSmallIntegerField(default=390),
        ),
        migrations.RunSQL(CRIAR, REMOVER),
    ]
