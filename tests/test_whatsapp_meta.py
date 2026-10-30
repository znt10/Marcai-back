"""O numero central pela API oficial da Meta (`whatsapp_meta.py`).

Os corpos de resposta seguem a documentacao da Cloud API: sucesso traz
`messages[0].id` (o wamid), erro traz `error.code`. O 131047 e' o "fora da
janela de 24h", o unico que faz o envio tentar de novo pelo template.
"""

import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import pytest

from app.services import whatsapp, whatsapp_meta

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/interno/whatsapp/meta"
HOST = "admin.localhost"


@pytest.fixture(autouse=True)
def _meta_ligada(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "meta")
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_NUMERO_ID", "1411744118692075")
    monkeypatch.setenv("META_WHATSAPP_TEMPLATE", "marcai_aviso")
    monkeypatch.setenv("META_WEBHOOK_TOKEN", "verifica")
    monkeypatch.setenv("META_APP_SECRET", "segredo-do-app")
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def _resposta(ok, corpo, status=200):
    r = Mock(ok=ok, status_code=status, text=json.dumps(corpo))
    r.json.return_value = corpo
    return r


ACEITA = _resposta(True, {"messages": [{"id": "wamid.ABC"}]})


# ------------------------------------------------------------------- envio


def test_com_template_sai_sempre_pelo_template_com_a_mensagem_achatada():
    """A Meta aceita texto fora da janela de 24h com 200 e so' falha depois,
    pelo webhook: tentar o texto primeiro faria a mensagem sumir."""
    with patch.object(whatsapp_meta.requests, "post", return_value=ACEITA) as post:
        aceita = whatsapp.enviar_a_equipe_aceita("83988982852", "Agenda de hoje:\n09:00 Ana\n\n10:00 Bia")
    assert aceita == whatsapp.Aceita("wamid.ABC", None)
    assert post.call_count == 1
    corpo = post.call_args.kwargs["json"]
    assert corpo["to"] == "5583988982852"
    assert corpo["type"] == "template"
    assert corpo["template"]["name"] == "marcai_aviso"
    assert corpo["template"]["language"] == {"code": "pt_BR"}
    assert corpo["template"]["components"][0]["parameters"][0]["text"] == "Agenda de hoje: · 09:00 Ana · 10:00 Bia"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
    assert "/1411744118692075/messages" in post.call_args.args[0]


def test_sem_template_sai_como_texto(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_TEMPLATE", "")
    with patch.object(whatsapp_meta.requests, "post", return_value=ACEITA) as post:
        assert whatsapp_meta.enviar("83988982852", "oi\nlinha 2") == "wamid.ABC"
    corpo = post.call_args.kwargs["json"]
    assert corpo["type"] == "text"
    assert corpo["text"]["body"] == "oi\nlinha 2"


def test_template_recusado_nao_sai_e_loga(caplog):
    nao_aprovado = _resposta(False, {"error": {"code": 132001}}, 400)
    with patch.object(whatsapp_meta.requests, "post", return_value=nao_aprovado):
        with caplog.at_level("ERROR"):
            assert whatsapp_meta.enviar("83988982852", "oi") is None
    assert "132001" in caplog.text


def test_erro_de_token_nao_sai_e_loga(caplog):
    token_vencido = _resposta(False, {"error": {"code": 190}}, 401)
    with patch.object(whatsapp_meta.requests, "post", return_value=token_vencido) as post:
        with caplog.at_level("ERROR"):
            assert whatsapp.enviar_pelo_central("83988982852", "codigo 1234") is False
    assert post.call_count == 1
    assert "401" in caplog.text


def test_falha_de_rede_nao_lanca():
    import requests

    with patch.object(whatsapp_meta.requests, "post", side_effect=requests.ConnectionError("boom")):
        assert whatsapp_meta.enviar("83988982852", "oi") is None


def test_sem_token_so_loga(monkeypatch, caplog):
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "")
    with patch.object(whatsapp_meta.requests, "post") as post:
        with caplog.at_level("INFO"):
            assert whatsapp_meta.enviar("83988982852", "oi") is None
    post.assert_not_called()
    assert "sem META_WHATSAPP_TOKEN" in caplog.text


def test_sem_provedor_meta_continua_pela_evolution(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "")
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "Marcai")
    resposta = _resposta(True, {"key": {"id": "x", "remoteJid": "j"}})
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        whatsapp.enviar_a_equipe("83988982852", "oi")
    assert "/message/sendText/Marcai" in post.call_args.args[0]


def test_achatar_corta_o_que_passa_do_limite():
    texto = whatsapp_meta.achatar("a" * 2000)
    assert len(texto) == 900
    assert texto.endswith("…")


# -------------------------------------------- o que a Meta nao tem


def test_numero_existe_continua_pela_evolution_quando_ela_esta_configurada(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "Antigo")
    barbearia = Mock(plano=whatsapp.PlanoBarbearia.COM_ZAP)
    resposta = _resposta(True, [{"exists": False}])
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.numero_existe(barbearia, "83988982852", "1.2.3.4") == "nao_existe"
    assert "/chat/whatsappNumbers/Antigo" in post.call_args.args[0]


def test_apagar_e_numero_existe_nao_vao_a_lugar_nenhum():
    barbearia = Mock(plano=whatsapp.PlanoBarbearia.COM_ZAP)
    with patch.object(whatsapp.requests, "post") as post, patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos("jid", "id") is False
        assert whatsapp.numero_existe(barbearia, "83988982852", "1.2.3.4") == "indeterminado"
    post.assert_not_called()
    delete.assert_not_called()


def test_estado_open_so_com_numero_verificado():
    verificado = _resposta(True, {"display_phone_number": "+55 83 8898-2852", "code_verification_status": "VERIFIED"})
    pendente = _resposta(True, {"code_verification_status": "NOT_VERIFIED"})
    with patch.object(whatsapp_meta.requests, "get", return_value=verificado):
        assert whatsapp.estado_da_instancia() == "open"
    with patch.object(whatsapp_meta.requests, "get", return_value=pendente):
        assert "nao verificado" in whatsapp.estado_da_instancia()


# ----------------------------------------------------------------- webhook


def test_webhook_responde_o_desafio_com_o_token_certo(client):
    r = client.get(
        ROTA,
        {"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"},
        headers={"host": HOST},
    )
    assert r.status_code == 200
    assert r.content == b"42"


def test_webhook_recusa_o_desafio_com_token_errado(client):
    r = client.get(
        ROTA,
        {"hub.mode": "subscribe", "hub.verify_token": "outro", "hub.challenge": "42"},
        headers={"host": HOST},
    )
    assert r.status_code == 403


def _assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(b"segredo-do-app", corpo, hashlib.sha256).hexdigest()


def test_webhook_assinado_e_aceito_sem_x_brutus_cliente(client, caplog):
    corpo = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [
            {"status": "failed", "recipient_id": "5583988982852", "errors": [{"code": 131026}]},
        ]}}]}],
    }).encode()
    with caplog.at_level("ERROR"):
        r = client.post(
            ROTA, corpo, content_type="application/json",
            headers={"host": HOST, "x-hub-signature-256": _assinar(corpo)},
        )
    assert r.status_code == 200
    assert r.json()["resultado"] == "falhas=1 recebidas=0"
    assert "131026" in caplog.text


def test_webhook_com_assinatura_errada_da_401(client):
    corpo = b'{"object": "whatsapp_business_account"}'
    r = client.post(
        ROTA, corpo, content_type="application/json",
        headers={"host": HOST, "x-hub-signature-256": "sha256=errada"},
    )
    assert r.status_code == 401


def test_meta_ligada_tira_a_pausa_do_cliente(monkeypatch):
    monkeypatch.setattr(whatsapp, "CLIENTE_SEM_WHATSAPP", True)
    assert whatsapp.cliente_sem_whatsapp() is False
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "")
    assert whatsapp.cliente_sem_whatsapp() is True
