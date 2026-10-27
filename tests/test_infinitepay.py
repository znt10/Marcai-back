import pytest
import requests
from django.test import override_settings

from app.services import infinitepay
from app.services.infinitepay import ErroDaInfinitePay

CONFIG = dict(
    INFINITEPAY_HANDLE="marcai",
    INFINITEPAY_API_KEY="",
    INFINITEPAY_WEBHOOK_SEGREDO="s3gredo",
)


class _Resposta:
    def __init__(self, status=200, corpo=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._corpo = corpo if corpo is not None else {}
        self.text = str(self._corpo)

    def json(self):
        return self._corpo


class _Chamadas(list):
    falso = None


@pytest.fixture
def chamadas(monkeypatch):
    """Troca o `requests.post` e guarda o que foi mandado. `chamadas.resposta`
    decide o que volta."""
    feitas = _Chamadas()

    def falso(url, json=None, headers=None, timeout=None):
        feitas.append({"url": url, "json": json, "headers": headers or {}, "timeout": timeout})
        r = falso.resposta
        if isinstance(r, Exception):
            raise r
        return r

    falso.resposta = _Resposta(200, {"url": "https://checkout.infinitepay.io/marcai/abc"})
    monkeypatch.setattr(infinitepay.requests, "post", falso)
    monkeypatch.setenv("URL_BASE", "https://usemarcai.online")
    feitas.falso = falso
    return feitas


def _criar():
    return infinitepay.criar_link(
        valor_centavos=6000, descricao="Mensalidade Marcaí - Brutus",
        referencia="c0b-1", barbearia_slug="brutus",
    )


@override_settings(**CONFIG)
def test_criar_link_manda_preco_em_centavos_e_order_nsu(chamadas):
    _criar()
    (c,) = chamadas
    assert c["url"] == "https://api.checkout.infinitepay.io/links"
    assert c["timeout"] == 10
    corpo = c["json"]
    assert corpo["handle"] == "marcai"
    assert corpo["items"] == [
        {"quantity": 1, "price": 6000, "description": "Mensalidade Marcaí - Brutus"}
    ]
    assert corpo["order_nsu"] == "c0b-1"
    assert corpo["redirect_url"] == "https://brutus.usemarcai.online/painel"
    assert corpo["webhook_url"] == (
        "https://brutus.usemarcai.online/api/interno/infinitepay?t=s3gredo"
    )


@override_settings(**CONFIG)
def test_criar_link_manda_api_key_so_quando_existe(chamadas):
    _criar()
    assert "X-Api-Key" not in chamadas[0]["headers"]
    with override_settings(INFINITEPAY_API_KEY="k3y"):
        _criar()
    assert chamadas[1]["headers"]["X-Api-Key"] == "k3y"


@override_settings(**CONFIG)
def test_criar_link_devolve_a_url(chamadas):
    assert _criar() == "https://checkout.infinitepay.io/marcai/abc"


@override_settings(**CONFIG)
def test_criar_link_aceita_o_campo_link(chamadas):
    chamadas.falso.resposta = _Resposta(200, {"link": "https://checkout.infinitepay.io/x"})
    assert _criar() == "https://checkout.infinitepay.io/x"


@override_settings(**CONFIG)
def test_resposta_sem_link_vira_erro(chamadas):
    chamadas.falso.resposta = _Resposta(200, {"ok": True})
    with pytest.raises(ErroDaInfinitePay):
        _criar()


@override_settings(**CONFIG)
def test_resposta_500_vira_erro(chamadas):
    chamadas.falso.resposta = _Resposta(500, {"erro": "x"})
    with pytest.raises(ErroDaInfinitePay):
        _criar()


@override_settings(**CONFIG)
def test_timeout_vira_erro(chamadas):
    chamadas.falso.resposta = requests.Timeout("lento")
    with pytest.raises(ErroDaInfinitePay):
        _criar()


@override_settings(**CONFIG)
def test_conferir_traduz_a_resposta(chamadas):
    chamadas.falso.resposta = _Resposta(200, {
        "success": True, "paid": True, "amount": 6000, "paid_amount": 6010,
        "installments": 1, "capture_method": "pix",
    })
    r = infinitepay.conferir(referencia="c0b-1", transacao="nsu-9", slug="fat-1")
    assert r == {"pago": True, "valor_centavos": 6000, "meio": "pix"}
    (c,) = chamadas
    assert c["url"] == "https://api.checkout.infinitepay.io/payment_check"
    assert c["json"] == {
        "handle": "marcai", "order_nsu": "c0b-1", "transaction_nsu": "nsu-9", "slug": "fat-1",
    }
    assert c["timeout"] == 10


@override_settings(**CONFIG)
def test_conferir_sem_paid_vira_erro(chamadas):
    chamadas.falso.resposta = _Resposta(200, {"success": False})
    with pytest.raises(ErroDaInfinitePay):
        infinitepay.conferir(referencia="c0b-1", transacao="nsu-9", slug="fat-1")


@override_settings(**CONFIG)
def test_segredo_confere_so_o_certo():
    assert infinitepay.segredo_confere("s3gredo") is True
    assert infinitepay.segredo_confere("outro") is False
    assert infinitepay.segredo_confere("ção") is False


@override_settings(INFINITEPAY_WEBHOOK_SEGREDO="")
def test_segredo_vazio_nunca_confere():
    assert infinitepay.segredo_confere("") is False


def test_configurada_pede_handle_e_segredo():
    with override_settings(**CONFIG):
        assert infinitepay.configurada() is True
    with override_settings(**{**CONFIG, "INFINITEPAY_HANDLE": ""}):
        assert infinitepay.configurada() is False
    with override_settings(**{**CONFIG, "INFINITEPAY_WEBHOOK_SEGREDO": ""}):
        assert infinitepay.configurada() is False
