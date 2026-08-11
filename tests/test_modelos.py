import pytest

from tenant.models import Barbearia, Barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"])


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
