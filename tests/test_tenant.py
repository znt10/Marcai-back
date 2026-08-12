import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_host_vira_barbearia(client, cenario):
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 200
    assert r.json()["barbearia"] == "Brutus"


def test_outro_host_vira_outra_barbearia(client, cenario):
    r = client.get("/api/saude", headers={"host": "dontony.localhost"})
    assert r.json()["barbearia"] == "Dom Tony"


def test_host_desconhecido_da_404(client, cenario):
    r = client.get("/api/saude", headers={"host": "naoexiste.localhost"})
    assert r.status_code == 404


def test_barbearia_desativada_da_404(client, cenario):
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(slug="brutus").update(ativo=False)
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 404


def test_host_do_admin_nao_e_barbearia(client, cenario):
    r = client.get("/api/saude", headers={"host": "admin.localhost"})
    assert r.status_code == 200
    assert r.json()["barbearia"] is None
    assert r.json()["admin"] is True
