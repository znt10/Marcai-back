"""A tela do cliente clara ou escura, escolhida pelo dono (07/11/2026).

Ideia de quem conhece cliente mais velho: tela muito preta cansa. O dono
troca entre o claro e o escuro da MESMA cor; a cor continua do admin.
"""

import uuid

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, papel="DONO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Zeca",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _put(client, paleta):
    return client.put(
        "/api/painel/paleta", {"paleta": paleta}, content_type="application/json",
        headers={"host": "brutus.localhost", **CABECALHO},
    )


def _paleta(barbearia_id):
    from tenant.models import Barbearia

    return Barbearia.objects.using("owner").get(id=barbearia_id).paleta


def _pintar(barbearia_id, paleta):
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(id=barbearia_id).update(paleta=paleta)


@pytest.mark.parametrize("de,para", [
    ("PRETO_ROSE", "BRANCO_ROSE"), ("BRANCO_ROSE", "PRETO_ROSE"),
    ("PRETO_AMARELO", "BRANCO_DOURADO"), ("BRANCO_DOURADO", "PRETO_AMARELO"),
])
def test_dono_troca_para_o_par_da_mesma_cor(client, cenario, de, para):
    b = cenario["brutus"]
    _pintar(b.id, de)
    _logar(client, _barbeiro(b.id), b.id)

    assert _put(client, para).status_code == 200
    assert _paleta(b.id) == para


def test_outra_cor_e_do_admin(client, cenario):
    b = cenario["brutus"]
    _pintar(b.id, "PRETO_ROSE")
    _logar(client, _barbeiro(b.id), b.id)

    r = _put(client, "BRANCO_DOURADO")
    assert r.status_code == 422
    assert _paleta(b.id) == "PRETO_ROSE"


def test_paleta_que_nao_existe_e_422(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    assert _put(client, "VERDE").status_code == 422


def test_mesma_paleta_nao_e_erro(client, cenario):
    b = cenario["brutus"]
    _pintar(b.id, "PRETO_ROSE")
    _logar(client, _barbeiro(b.id), b.id)
    assert _put(client, "PRETO_ROSE").status_code == 200


def test_barbeiro_comum_nao_troca(client, cenario):
    b = cenario["brutus"]
    _pintar(b.id, "PRETO_ROSE")
    _logar(client, _barbeiro(b.id, papel="BARBEIRO"), b.id)

    assert _put(client, "BRANCO_ROSE").status_code == 403
    assert _paleta(b.id) == "PRETO_ROSE"


def test_so_mexe_na_propria_casa(client, cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    _pintar(b.id, "PRETO_ROSE")
    _pintar(outra.id, "PRETO_ROSE")
    _logar(client, _barbeiro(b.id), b.id)

    assert _put(client, "BRANCO_ROSE").status_code == 200
    assert _paleta(outra.id) == "PRETO_ROSE"


def test_a_tela_publica_mostra_a_troca(client, cenario):
    b = cenario["brutus"]
    _pintar(b.id, "PRETO_AMARELO")
    _logar(client, _barbeiro(b.id), b.id)
    assert _put(client, "BRANCO_DOURADO").status_code == 200

    r = client.get("/api/barbearia", headers={"host": "brutus.localhost"})
    assert r.json()["paleta"] == "BRANCO_DOURADO"
