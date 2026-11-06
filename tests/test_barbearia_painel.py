import uuid

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0)
    return host


def test_get_qualquer_sessao_le_a_frase(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.get("/api/painel/barbearia", headers={"host": host})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["nome"] == b.nome
    assert corpo["horarioResumo"] is None


def test_painel_devolve_a_logo(client, cenario):
    """A tela Equipe mostra a logo atual sobre o fundo da paleta do cliente:
    precisa da logo, do tipo e da paleta."""
    from tenant.models import Barbearia

    b = cenario["brutus"]
    logo = "data:image/png;base64,iVBORw0KGgo="
    Barbearia.objects.using("owner").filter(id=b.id).update(logo_url=logo)
    host = _logar(client, _barbeiro(b.id, papel="DONO"), b.id)

    corpo = client.get("/api/painel/barbearia", headers={"host": host}).json()

    assert corpo["logoUrl"] == logo
    assert (corpo["tipo"], corpo["paleta"]) == ("BARBEARIA", "PRETO_AMARELO")


def test_patch_exige_ser_dono(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.patch(
        "/api/painel/barbearia", {"horarioResumo": "Seg a sáb, 9h-20h"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono muda isso."


def test_patch_grava_e_get_reflete_na_hora(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.patch(
        "/api/painel/barbearia", {"horarioResumo": "Seg a sáb, 9h-20h"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    corpo = client.get("/api/painel/barbearia", headers={"host": host}).json()
    assert corpo["horarioResumo"] == "Seg a sáb, 9h-20h"


def test_patch_frase_curta_e_422(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.patch(
        "/api/painel/barbearia", {"horarioResumo": "9h"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422
