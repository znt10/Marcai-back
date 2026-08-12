import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.mark.parametrize("caminho", ["/admin", "/admin/qualquer", "/api/admin/barbearias"])
def test_admin_nao_existe_fora_do_host_do_admin(client, cenario, caminho):
    r = client.get(caminho, headers={"host": "brutus.localhost"})
    # 404, nunca 403: 403 confirmaria que a rota existe.
    assert r.status_code == 404


def test_rota_inventada_sob_o_prefixo_tambem_nasce_protegida(client, cenario):
    # A barreira e POSICIONAL. Rota que ainda nao existe ja responde 404 pelo
    # mesmo motivo que as que existem — e por isso a fatia 6 nao precisa
    # lembrar de proteger nada.
    r = client.get("/api/admin/inventada/agora", headers={"host": "brutus.localhost"})
    assert r.status_code == 404
