from django.db import models


class Barbearia(models.Model):
    """A tabela de tenant. Unica sem barbeariaId e unica fora do RLS — ela e
    lida ANTES de existir tenant, para traduzir subdominio em id, e por isso e
    protegida por GRANT (REVOKE INSERT/UPDATE/DELETE) e nao por politica.
    """

    # TextField, nao UUIDField: o Prisma declara `id String @id @default(uuid())`
    # sem `@db.Uuid` (front/prisma/schema.prisma:29) — o valor e um uuid, a
    # coluna e TEXT, e as duas coisas nao sao a mesma. UUIDField faz o psycopg3
    # mandar o parametro tipado como `uuid` (dumper com oid=UUID_OID); INSERT
    # passa porque uuid->text e cast de atribuicao, mas um `filter(id=...)`
    # compara `text = uuid`, que nao resolve, e o WHERE nao acha nada.
    id = models.TextField(primary_key=True, db_column="id")
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

    # TextField pelo mesmo motivo de Barbearia.id acima: a coluna do Prisma e
    # TEXT, e UUIDField mandaria o parametro tipado `uuid` contra uma coluna
    # `text` — o INSERT passa (uuid->text e cast de atribuicao) mas o
    # `filter(barbearia_id=...)` nao, porque `text = uuid` nao resolve. Esta
    # e a coluna sobre a qual o teste de isolamento de RLS e construido.
    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    nome = models.TextField(db_column="nome")
    whatsapp = models.TextField(db_column="whatsapp")
    ativo = models.BooleanField(db_column="ativo")

    class Meta:
        managed = False
        db_table = "Barbeiro"
