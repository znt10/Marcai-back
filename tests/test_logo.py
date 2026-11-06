"""A logo da casa — guardada como data URL em `Barbearia.logo_url`.

Mesmo jeito da foto do barbeiro (`test_foto.py`): o navegador reduz antes de
mandar, sem cortar, e o servidor NAO confia nisso. Diferente da foto, so' o
DONO mexe: a logo e' da casa, nao de quem atende.
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
        "/api/painel/logo", corpo,
        content_type="application/json", headers={"host": host, **CABECALHO},
    )


def _logo_no_banco(barbearia_id):
    from tenant.models import Barbearia

    return Barbearia.objects.using("owner").get(id=barbearia_id).logo_url


def _dono_logado(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    return b, _logar(client, dono, b.id)


def test_dono_poe_a_logo(client, cenario):
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": _data_url()})

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert _logo_no_banco(b.id).startswith("data:image/webp;base64,")


def test_tirar_a_logo_volta_ao_padrao(client, cenario):
    b, host = _dono_logado(client, cenario)
    _put(client, host, {"logo": _data_url()})

    assert _put(client, host, {"logo": None}).status_code == 200
    assert _logo_no_banco(b.id) is None


def test_logo_de_uma_casa_nao_vaza_para_a_outra(client, cenario):
    b, host = _dono_logado(client, cenario)

    _put(client, host, {"logo": _data_url()})

    assert _logo_no_banco(cenario["dontony"].id) is None


def test_barbeiro_nao_troca_a_logo(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = _put(client, host, {"logo": _data_url()})

    assert r.status_code == 403
    assert r.json() == {"erro": "Só o dono muda a logo."}
    assert _logo_no_banco(b.id) is None


def test_sem_sessao_nao_entra(client, cenario):
    r = _put(client, "brutus.localhost", {"logo": _data_url()})

    assert r.status_code == 401
    assert _logo_no_banco(cenario["brutus"].id) is None


def test_svg_e_recusado(client, cenario):
    """SVG e' imagem que carrega script, e ela iria parar num `<img>` servido
    pelo proprio dominio da casa."""
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": _data_url("image/svg+xml", b"<svg onload=alert(1)>")})

    assert r.status_code == 422
    assert r.json() == {"erro": "Essa imagem não serve. Manda a logo em JPG, PNG ou WebP."}
    assert _logo_no_banco(b.id) is None


def test_url_comum_e_recusada(client, cenario):
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": "https://exemplo.com/logo.png"})

    assert r.status_code == 422
    assert r.json() == {"erro": "Manda a logo pelo botão da tela."}


def test_logo_grande_demais_e_recusada(client, cenario):
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": _data_url(bytes_=b"x" * (60 * 1024 + 1))})

    assert r.status_code == 422
    assert r.json() == {"erro": "A logo ficou grande demais. Tenta outra?"}
    assert _logo_no_banco(b.id) is None


def test_logo_no_limite_passa(client, cenario):
    """60 KB e' o teto, inclusive: a mesma conta que o navegador faz."""
    b, host = _dono_logado(client, cenario)

    assert _put(client, host, {"logo": _data_url(bytes_=b"x" * (60 * 1024))}).status_code == 200


def test_base64_quebrado_e_recusado(client, cenario):
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": "data:image/png;base64,@@@"})

    assert r.status_code == 422
    assert r.json()["erro"]


def test_logo_que_nao_e_texto_e_recusada(client, cenario):
    b, host = _dono_logado(client, cenario)

    r = _put(client, host, {"logo": 123})

    assert r.status_code == 422
    assert r.json() == {"erro": "Manda a logo pelo botão da tela."}
