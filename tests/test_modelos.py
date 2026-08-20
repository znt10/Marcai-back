import pytest

from tenant.models import Barbearia, Barbeiro

# transaction=True e obrigatorio aqui pelas mesmas duas razoes que valem para
# todo outro arquivo de teste de banco deste repo (Global Constraint):
#
# 1. Sem ele, pytest-django embrulha os dois aliases numa unica TestCase
#    atomica. O TRUNCATE da fixture `limpar_banco` roda como `owner` e pede
#    AccessExclusiveLock em Barbearia; qualquer leitura pelo alias `default`
#    (mesmo em OUTRO teste, na mesma sessao) fica esperando esse lock para
#    sempre — a suite trava sem mensagem nenhuma em vez de falhar. Este
#    arquivo so escapa disso hoje porque nenhum dos tres testes le por
#    `default` (o unico que le usa `.using("owner")|` explicitamente); e
#    latente, e este e o arquivo obvio para a proxima fatia acrescentar teste
#    de model.
# 2. TestCase-owned atomic tambem e isento da checagem de durabilidade do
#    Django — entao um `com_barbearia(durable=True)` chamado de dentro de um
#    teste sem transaction=True degrada silenciosamente para um savepoint
#    comum em vez de barrar o aninhamento, reabrindo a troca de tenant que o
#    durable=True existe para impedir.
pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_le_a_barbearia_que_o_cenario_criou(cenario):
    b = Barbearia.objects.using("owner").get(slug="brutus")
    assert b.nome == "Brutus"
    assert b.ativo is True


def test_o_django_e_dono_das_tabelas():
    """O teste que este arquivo tinha aqui provava o CONTRARIO: que todo
    `db_column` batia com o nome que o Prisma tinha dado (`horarioResumo`,
    `whatsappContato`, `barbeariaId`) e que `managed` era False. Ele era a rede
    de um acoplamento — um `db_column` esquecido nao quebrava o Django, quebrava
    o lado que ainda era Prisma, e o sintoma aparecia longe da causa.

    A fatia 1 dissolveu o acoplamento: nao ha mais um segundo dono do schema
    para divergir. O que substitui aquela rede e' esta afirmacao, e ela vale
    para os oito models de uma vez — `managed=False` num deles significaria
    uma tabela que o `migrate` nao cria e que ninguem mais cria por ele.
    """
    from django.apps import apps

    for model in apps.get_app_config("tenant").get_models():
        assert model._meta.managed is True, model.__name__


def test_as_colunas_sao_snake_case():
    """O contrario exato do teste antigo. `horarioResumo` virou
    `horario_resumo` e `barbeariaId` virou `barbearia_id` — sem `db_column`
    nenhum, que e o ponto: o nome da coluna passa a ser derivado do nome do
    campo, e nao mantido a mao em sincronia com um schema.prisma.

    `barbearia_id` merece a mencao explicita porque ele NAO e mais um campo de
    texto e sim a coluna de uma ForeignKey — o atributo Python continua se
    chamando igual (e por isso todo `filter(barbearia_id=...)` do repo
    sobreviveu intocado), mas agora ha uma FK de verdade atras dele.
    """
    campos = {f.name: f.column for f in Barbearia._meta.get_fields() if hasattr(f, "column")}
    assert campos["horario_resumo"] == "horario_resumo"
    assert campos["whatsapp_contato"] == "whatsapp_contato"
    assert campos["criado_em"] == "criado_em"
    assert Barbearia._meta.db_table == "tenant_barbearia"

    campos = {f.name: f.column for f in Barbeiro._meta.get_fields() if hasattr(f, "column")}
    assert campos["barbearia"] == "barbearia_id"
    assert Barbeiro._meta.db_table == "tenant_barbeiro"


def test_o_id_e_uuid_de_verdade():
    """Enquanto o Prisma era dono, `id` era TEXT — ele declara
    `String @id @default(uuid())` sem `@db.Uuid`, entao o VALOR era um uuid e o
    TIPO nao. Os models espelhavam isso com TextField, e o comentario que
    justificava a escolha era o mais longo do arquivo: com UUIDField, o psycopg
    mandava o parametro tipado `uuid`, o INSERT passava por cast de atribuicao
    e o `filter(id=...)` nao achava nada, porque `text = uuid` nao resolve.

    Aquela classe inteira de defeito deixa de ser possivel quando os dois lados
    falam `uuid`. Este teste guarda a virada.
    """
    from django.db import models

    assert isinstance(Barbearia._meta.get_field("id"), models.UUIDField)
    assert isinstance(Barbeiro._meta.get_field("id"), models.UUIDField)
    assert Barbeiro._meta.get_field("barbearia").target_field.column == "id"
