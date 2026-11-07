from django.db import migrations

# O dono passa a trocar a tela do cliente entre claro e escuro (07/11/2026):
# GRANT por coluna, como a frase do horario (0002), a hora da lista (0009) e
# a logo (0020). Qual paleta pode e' regra do servico (`trocar_paleta`).
CRIAR = ["GRANT UPDATE (paleta) ON tenant_barbearia TO brutus_app;"]
REMOVER = ["REVOKE UPDATE (paleta) ON tenant_barbearia FROM brutus_app;"]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0024_grupo_de_servico")]

    operations = [migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER)]
