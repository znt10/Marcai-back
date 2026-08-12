import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_saude_responde_ok(client, cenario):
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
