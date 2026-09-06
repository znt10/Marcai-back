"""A foto do barbeiro — guardada como data URL na coluna que ja existia.

Sem storage de arquivo: `foto_url` e' TEXT desde a primeira migracao, e a foto
chega ja' recortada e reduzida pelo navegador. O servidor NAO confia nisso —
cliente e' sugestao, servidor e' regra — e e' o que estes testes guardam.
"""

import base64
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
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )
    return host


def _data_url(mime="image/webp", bytes_=b"RIFF____WEBPVP8 fake"):
    return f"data:{mime};base64,{base64.b64encode(bytes_).decode()}"


def _put(client, host, corpo):
    return client.put(
        "/api/painel/foto", corpo,
        content_type="application/json", headers={"host": host, **CABECALHO},
    )


def test_barbeiro_poe_a_propria_foto(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = _put(client, host, {"foto": _data_url()})
    assert r.status_code == 200

    from tenant.models import Barbeiro

    assert Barbeiro.objects.using("owner").get(id=barbeiro.id).foto_url.startswith("data:image/webp")


def test_apagar_a_foto_volta_para_o_circulo_vazio(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    _put(client, host, {"foto": _data_url()})

    assert _put(client, host, {"foto": None}).status_code == 200

    from tenant.models import Barbeiro

    assert Barbeiro.objects.using("owner").get(id=barbeiro.id).foto_url is None


def test_svg_e_recusado(client, cenario):
    """SVG e' imagem que carrega script, e ela iria parar num `<img src>`
    servido pelo proprio dominio da barbearia."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = _put(client, host, {"foto": _data_url("image/svg+xml", b"<svg onload=alert(1)>")})
    assert r.status_code == 422


def test_url_comum_e_recusada(client, cenario):
    """So' data URL: um `https://...` faria o produto buscar imagem de dominio
    de terceiro na primeira tela do cliente."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    assert _put(client, host, {"foto": "https://site.com/foto.jpg"}).status_code == 422


def test_foto_grande_demais_e_recusada(client, cenario):
    """A vitrine e' renderizada no SERVIDOR: a foto entra embutida no HTML da
    primeira tela. Sem teto, uma foto de camera mata justamente essa tela."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = _put(client, host, {"foto": _data_url(bytes_=b"x" * 200_000)})
    assert r.status_code == 422
    assert "grande" in r.json()["erro"].lower()


def test_base64_quebrado_e_recusado(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    assert _put(client, host, {"foto": "data:image/webp;base64,!!!nao-e-base64!!!"}).status_code == 422


def test_dono_troca_a_foto_do_colega(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    colega = _barbeiro(b.id, "Rael")
    host = _logar(client, dono, b.id)

    r = _put(client, host, {"foto": _data_url(), "barbeiroId": colega.id})
    assert r.status_code == 200

    from tenant.models import Barbeiro

    assert Barbeiro.objects.using("owner").get(id=colega.id).foto_url is not None


def test_barbeiro_nao_troca_a_foto_do_colega(client, cenario):
    """Mesma regra de horarios e servicos: 404, nunca 403 — 403 confirmaria
    que o colega existe."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    colega = _barbeiro(b.id, "Rael")
    host = _logar(client, barbeiro, b.id)

    assert _put(client, host, {"foto": _data_url(), "barbeiroId": colega.id}).status_code == 404

    from tenant.models import Barbeiro

    assert Barbeiro.objects.using("owner").get(id=colega.id).foto_url is None


def test_sem_sessao_nao_entra(client, cenario):
    b = cenario["brutus"]
    r = client.put(
        "/api/painel/foto", {"foto": _data_url()},
        content_type="application/json",
        headers={"host": "brutus.localhost", **CABECALHO},
    )
    assert r.status_code == 401


def test_eu_devolve_a_foto_para_o_cabecalho_do_painel(client, cenario):
    """Sem isto o cabeçalho nao teria o que desenhar, e a pessoa nao veria a
    foto que acabou de mandar sem recarregar tudo."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    antes = client.get("/api/auth/eu", headers={"host": host, **CABECALHO})
    assert antes.json()["fotoUrl"] is None

    _put(client, host, {"foto": _data_url()})
    depois = client.get("/api/auth/eu", headers={"host": host, **CABECALHO})
    assert depois.json()["fotoUrl"].startswith("data:image/webp")
