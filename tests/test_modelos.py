import pytest

from tenant.models import Barbearia

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
