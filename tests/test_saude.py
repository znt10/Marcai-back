import pytest
from fabricas import criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_traz_o_tenant_resolvido(client, cenario):
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 200
    assert r.json()["barbearia"] == "Brutus"
    assert r.json()["slug"] == "brutus"


def test_conta_sob_o_rls_e_o_numero_muda_por_barbearia(client, cenario):
    from tenant.models import Barbeiro
    from tenant.rls import com_barbearia

    # A Dom Tony ganha um segundo barbeiro: se o numero fosse global, as duas
    # respostas seriam iguais e o teste passaria sem provar nada.
    import uuid

    criar_barbeiro(
        id=str(uuid.uuid4()),
        barbearia_id=cenario["dontony"].id,
        nome="Segundo da Dom Tony",
        whatsapp="11955556666",
        ativo=True,
    )

    um = client.get("/api/saude", headers={"host": "brutus.localhost"}).json()
    dois = client.get("/api/saude", headers={"host": "dontony.localhost"}).json()

    assert um["barbeiros"] == 1
    assert dois["barbeiros"] == 2


def test_o_cookie_vai_e_volta(client, cenario):
    primeira = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert primeira.json()["recebeu_cookie"] is False
    assert primeira.cookies["saude"]["httponly"] is True
    # Host-only: sem atributo domain. E o que faz o cookie atravessar da porta
    # 8000 para a 3000 sem nenhum truque, porque cookie ignora porta.
    assert primeira.cookies["saude"]["domain"] == ""

    segunda = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert segunda.json()["recebeu_cookie"] is True
