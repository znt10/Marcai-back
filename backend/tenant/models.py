from django.db import models


class Barbearia(models.Model):
    """A tabela de tenant. Unica sem barbeariaId e unica fora do RLS — ela e
    lida ANTES de existir tenant, para traduzir subdominio em id, e por isso e
    protegida por GRANT (REVOKE INSERT/UPDATE/DELETE) e nao por politica.
    """

    id = models.UUIDField(primary_key=True, db_column="id")
    slug = models.TextField(unique=True, db_column="slug")
    nome = models.TextField(db_column="nome")
    endereco = models.TextField(db_column="endereco")
    # Nulo ate o DONO preencher: o admin da plataforma nao sabe o horario da
    # barbearia. Nulo e string vazia seriam dois jeitos de dizer a mesma coisa.
    horario_resumo = models.TextField(null=True, db_column="horarioResumo")
    whatsapp_contato = models.TextField(db_column="whatsappContato")
    ativo = models.BooleanField(db_column="ativo")
    criado_em = models.DateTimeField(db_column="criadoEm")

    class Meta:
        managed = False
        db_table = "Barbearia"


class Barbeiro(models.Model):
    """Existe nesta fatia por um motivo so: e a tabela de tenant que o teste de
    RLS conta para provar que o escopo funciona. Os campos que a fatia 1 vai
    precisar entram la.
    """

    id = models.UUIDField(primary_key=True, db_column="id")
    barbearia_id = models.UUIDField(db_column="barbeariaId")
    nome = models.TextField(db_column="nome")
    whatsapp = models.TextField(db_column="whatsapp")
    ativo = models.BooleanField(db_column="ativo")

    class Meta:
        managed = False
        db_table = "Barbeiro"
