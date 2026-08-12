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


def test_nomes_de_coluna_batem_com_o_prisma():
    # Um db_column esquecido nao quebra o Django: quebra o lado que ainda e
    # Prisma, e o sintoma aparece longe da causa. Este teste e a rede.
    campos = {f.name: f.column for f in Barbearia._meta.get_fields() if hasattr(f, "column")}
    assert campos["horario_resumo"] == "horarioResumo"
    assert campos["whatsapp_contato"] == "whatsappContato"
    assert campos["criado_em"] == "criadoEm"
    assert Barbearia._meta.db_table == "Barbearia"
    assert Barbearia._meta.managed is False


def test_nomes_de_coluna_do_barbeiro_batem_com_o_prisma():
    # barbeariaId e o rename nao trivial que sustenta o teste de RLS da
    # fatia 6 — sem esta rede, um db_column esquecido aqui so quebraria lá,
    # longe desta tarefa.
    campos = {f.name: f.column for f in Barbeiro._meta.get_fields() if hasattr(f, "column")}
    assert campos["barbearia_id"] == "barbeariaId"
    assert Barbeiro._meta.db_table == "Barbeiro"
    assert Barbeiro._meta.managed is False
