import django.db.models.deletion
from django.db import migrations, models

# O aguardando segura o horario: a restricao do banco passa a valer para
# CONFIRMADO e AGUARDANDO_PAGAMENTO (a mesma lista de `slots_do_dia`).
# EXPIRADO e cancelados seguem fora. Refazer e' DROP + ADD porque um EXCLUDE
# nao se altera. Na volta, a restricao antiga so' sobe se nao houver
# aguardando sobreposto a um confirmado — cabe ao operador limpar antes.
EXCLUDE_NOVO = [
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT agendamento_sem_sobreposicao;",
    """
    ALTER TABLE tenant_agendamento
      ADD CONSTRAINT agendamento_sem_sobreposicao
      EXCLUDE USING gist (
        barbeiro_id WITH =,
        tstzrange(inicio, fim, '[)') WITH &&
      )
      WHERE (status IN ('CONFIRMADO', 'AGUARDANDO_PAGAMENTO'));
    """,
]
EXCLUDE_ANTIGO = [
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT agendamento_sem_sobreposicao;",
    """
    ALTER TABLE tenant_agendamento
      ADD CONSTRAINT agendamento_sem_sobreposicao
      EXCLUDE USING gist (
        barbeiro_id WITH =,
        tstzrange(inicio, fim, '[)') WITH &&
      )
      WHERE (status = 'CONFIRMADO');
    """,
]

# O Django nao grava o ON DELETE no banco (DO_NOTHING vira NO ACTION) e
# `Agendamento` esta dentro do RLS enquanto `Cobranca` esta fora: apagar o
# agendamento como `brutus_app` nao pode depender de um UPDATE em
# `tenant_cobranca` que ele nao tem. O gatilho de RI roda com os direitos do
# DONO da tabela, como na FK de `informada_por` (0015).
FK_SET_NULL = [
    """
    ALTER TABLE tenant_cobranca ADD CONSTRAINT tenant_cobranca_agendamento_fk
      FOREIGN KEY (agendamento_id) REFERENCES tenant_agendamento(id)
      ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    """
]
SEM_FK = ["ALTER TABLE tenant_cobranca DROP CONSTRAINT tenant_cobranca_agendamento_fk;"]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0016_pix_do_barbeiro")]

    operations = [
        migrations.AlterField(
            model_name="agendamento",
            name="status",
            field=models.CharField(
                choices=[
                    ("CONFIRMADO", "Confirmado"),
                    ("AGUARDANDO_PAGAMENTO", "Aguardando Pagamento"),
                    ("EXPIRADO", "Expirado"),
                    ("CANCELADO_CLIENTE", "Cancelado Cliente"),
                    ("CANCELADO_BARBEIRO", "Cancelado Barbeiro"),
                ],
                default="CONFIRMADO", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="cobranca",
            name="agendamento",
            field=models.OneToOneField(
                blank=True, null=True, db_constraint=False,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="cobranca", to="tenant.agendamento",
            ),
        ),
        migrations.RunSQL(FK_SET_NULL, SEM_FK),
        migrations.RunSQL(EXCLUDE_NOVO, EXCLUDE_ANTIGO),
    ]
