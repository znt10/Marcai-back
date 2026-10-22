import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# `Assinatura` e `Cobranca` ficam FORA do RLS, como `tenant_barbearia`: a busca
# de centavos livres atravessa barbearias. A protecao e' o GRANT. O
# `ALTER DEFAULT PRIVILEGES` do init-db.sh daria DML ao `brutus_app` em tabela
# nova; aqui ele perde a escrita e fica so' com a leitura (o middleware da
# trava pode ler). Escrever, so' o `brutus_admin`, que ja nasce com DML.
TABELAS = ["tenant_assinatura", "tenant_cobranca"]
CRIAR = [f"REVOKE INSERT, UPDATE, DELETE ON {t} FROM brutus_app;" for t in TABELAS]
REMOVER = [f"GRANT INSERT, UPDATE, DELETE ON {t} TO brutus_app;" for t in TABELAS]


# O Django nao grava o ON DELETE no banco (DO_NOTHING vira NO ACTION), entao a
# FK de `informada_por` e' feita aqui, a mao. O gatilho de RI roda com os direitos do DONO da tabela,
# nao do `brutus_app` que apaga o barbeiro.
FK_SET_NULL = [
    """
    ALTER TABLE tenant_cobranca ADD CONSTRAINT tenant_cobranca_informada_por_fk
      FOREIGN KEY (informada_por_id) REFERENCES tenant_barbeiro(id)
      ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    """
]


def isentar_existentes(apps, schema_editor):
    """Toda barbearia que ja existe nasce isenta: ninguem pode acordar com o
    painel travado por uma cobranca que nao combinou. As combinadas viram
    pelo admin depois.

    `schema_editor.connection` e' o `owner`, que cria as tabelas e nao tem
    RLS sobre `tenant_barbearia` (fora do RLS)."""
    from app.services.mensalidade.datas import dia_de_vencimento_para
    from app.services.mensalidade.situacao import hoje_em_sao_paulo
    from django.utils import timezone

    Barbearia = apps.get_model("tenant", "Barbearia")
    Assinatura = apps.get_model("tenant", "Assinatura")
    alias = schema_editor.connection.alias
    hoje = hoje_em_sao_paulo(timezone.now())
    dia = dia_de_vencimento_para(hoje)
    Assinatura.objects.using(alias).bulk_create(
        [
            Assinatura(
                barbearia_id=b_id, valor_centavos=0, dia_de_vencimento=dia,
                paga_ate=hoje, isenta=True,
            )
            for b_id in Barbearia.objects.using(alias).values_list("id", flat=True)
        ]
    )


class Migration(migrations.Migration):
    dependencies = [("tenant", "0014_custo")]

    operations = [
        migrations.CreateModel(
            name="Assinatura",
            fields=[
                ("barbearia", models.OneToOneField(on_delete=django.db.models.deletion.RESTRICT, primary_key=True, related_name="assinatura", serialize=False, to="tenant.barbearia")),
                ("valor_centavos", models.PositiveIntegerField(default=0)),
                ("dia_de_vencimento", models.PositiveSmallIntegerField()),
                ("paga_ate", models.DateField()),
                ("isenta", models.BooleanField(default=False)),
                ("nunca_bloquear", models.BooleanField(default=False)),
                ("ultimo_aviso", models.TextField(blank=True, default="")),
                ("ultimo_aviso_paga_ate", models.DateField(blank=True, null=True)),
                ("atualizada_em", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name="Cobranca",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("motivo", models.TextField(choices=[("MENSALIDADE", "Mensalidade"), ("AGENDAMENTO", "Agendamento")])),
                ("chave_pix", models.TextField()),
                ("valor_base_centavos", models.PositiveIntegerField()),
                ("valor_centavos", models.PositiveIntegerField()),
                ("copia_e_cola", models.TextField()),
                ("status", models.TextField(choices=[("ABERTA", "Aberta"), ("PAGA", "Paga"), ("EXPIRADA", "Expirada"), ("CANCELADA", "Cancelada")], default="ABERTA")),
                ("criada_em", models.DateTimeField(default=django.utils.timezone.now)),
                ("expira_em", models.DateTimeField(blank=True, null=True)),
                ("informada_em", models.DateTimeField(blank=True, null=True)),
                ("recusada_em", models.DateTimeField(blank=True, null=True)),
                ("paga_em", models.DateTimeField(blank=True, null=True)),
                ("como_foi_paga", models.TextField(blank=True, choices=[("MANUAL", "Manual"), ("VIGIA", "Vigia"), ("REGISTRO", "Registro")], null=True)),
                ("paga_ate_depois", models.DateField(blank=True, null=True)),
                ("observacao", models.TextField(blank=True, default="")),
                ("barbearia", models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="cobrancas", to="tenant.barbearia")),
                ("informada_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, db_constraint=False, related_name="+", to="tenant.barbeiro")),
            ],
        ),
        migrations.AddConstraint(
            model_name="cobranca",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "ABERTA")), fields=("chave_pix", "valor_centavos"), name="cobranca_aberta_por_chave_e_valor"),
        ),
        migrations.RunSQL(FK_SET_NULL, migrations.RunSQL.noop),
        migrations.RunSQL(CRIAR, REMOVER),
        migrations.RunPython(isentar_existentes, migrations.RunPython.noop),
    ]
