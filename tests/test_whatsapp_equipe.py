"""A equipe pelo chip da Evolution com a Meta ligada (spec 2026-11-03).

Com `WHATSAPP_EQUIPE_PELA_EVOLUTION`, o que vai para barbeiro e dono sai pela
Evolution — de graca, e a lista refeita volta a apagar a anterior. O que vai
para o cliente continua pela Meta. Os dois `requests` sao trocados em
separado: e' o unico jeito de saber QUEM foi chamado.
"""

import json
import logging
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from app.services import whatsapp
from tenant.models import Barbearia, TipoMensagem

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _meta_e_evolution(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "meta")
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_NUMERO_ID", "1411744118692075")
    monkeypatch.setenv("META_WHATSAPP_TEMPLATE", "marcai_aviso")
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "central")
    monkeypatch.delenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", raising=False)


@pytest.fixture
def chave(monkeypatch):
    monkeypatch.setenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", "1")


def _meta_ok():
    corpo = {"messages": [{"id": "wamid.ABC"}]}
    r = Mock(ok=True, status_code=200, text=json.dumps(corpo))
    r.json.return_value = corpo
    return r


def _evolution_ok():
    r = Mock(ok=True, status_code=201)
    r.json.return_value = {
        "key": {"id": "3EB0X", "remoteJid": "5583988887777@s.whatsapp.net"},
        "status": "PENDING",
    }
    return r


class _Chamadas:
    """As chamadas de um lado so'. `whatsapp.requests` e `whatsapp_meta.requests`
    sao o MESMO modulo, entao um patch so' e a URL diz quem foi chamado."""

    def __init__(self):
        self.call_args_list = []

    @property
    def call_count(self):
        return len(self.call_args_list)


@contextmanager
def _os_dois(evolution=None):
    meta, evo = _Chamadas(), _Chamadas()

    def post(url, *args, **kwargs):
        chamada = Mock(args=(url, *args), kwargs=kwargs)
        if url.startswith("https://graph.facebook.com/"):
            meta.call_args_list.append(chamada)
            return _meta_ok()
        evo.call_args_list.append(chamada)
        return evolution or _evolution_ok()

    with patch.object(whatsapp.requests, "post", side_effect=post):
        yield meta, evo


# ------------------------------------------------------------------ a chave


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", " 1 "])
def test_chave_ligada_reconhece(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", valor)
    assert whatsapp.equipe_pela_evolution() is True


@pytest.mark.parametrize("valor", ["", "0", "false"])
def test_chave_desligada(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", valor)
    assert whatsapp.equipe_pela_evolution() is False


def test_sem_a_variavel_a_chave_fica_desligada():
    assert whatsapp.equipe_pela_evolution() is False


# ------------------------------------------------------------------- equipe


def test_sem_chave_equipe_vai_pela_meta():
    with _os_dois() as (meta, evo):
        aceita = whatsapp.enviar_a_equipe_aceita("83988887777", "Bom dia!")
    assert aceita == whatsapp.Aceita("wamid.ABC", None)
    assert meta.call_count == 1
    assert evo.call_count == 0


def test_com_chave_equipe_vai_pela_evolution(chave):
    with _os_dois() as (meta, evo):
        aceita = whatsapp.enviar_a_equipe_aceita("83988887777", "Bom dia!")
        whatsapp.enviar_a_equipe("83988887777", "Novo horario")
    assert aceita == whatsapp.Aceita("3EB0X", "5583988887777@s.whatsapp.net")
    assert meta.call_count == 0
    assert evo.call_count == 2
    assert all(c.args[0] == "http://evolution:8080/message/sendText/central" for c in evo.call_args_list)


def test_com_chave_cliente_continua_pela_meta(chave, cenario):
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    b.plano = "COM_ZAP"
    with _os_dois() as (meta, evo):
        assert whatsapp.enviar_ao_cliente(
            b, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO, cliente_nome="Ana",
        ) is True
        assert whatsapp.enviar_pelo_central("11977778888", "Seu codigo: 123456") is True
    assert meta.call_count == 2
    assert evo.call_count == 0


def test_com_chave_sem_evolution_url_nao_cai_na_meta(chave, monkeypatch, caplog):
    monkeypatch.delenv("EVOLUTION_API_URL")
    caplog.set_level(logging.INFO)
    with _os_dois() as (meta, evo):
        aceita = whatsapp.enviar_a_equipe_aceita("83988887777", "Bom dia!")
    assert aceita is None
    assert meta.call_count == 0
    assert evo.call_count == 0
    assert "sem EVOLUTION_API_URL" in caplog.text


def test_com_chave_falha_da_evolution_nao_cai_na_meta(chave):
    recusa = Mock(ok=False, status_code=400, text="instance not connected")
    with _os_dois(evolution=recusa) as (meta, evo):
        aceita = whatsapp.enviar_a_equipe_aceita("83988887777", "Bom dia!")
    assert aceita is None
    assert evo.call_count == 1
    assert meta.call_count == 0


# ------------------------------------------------------------------- apagar


def test_com_chave_apagar_vai_pela_evolution(chave):
    with patch.object(whatsapp.requests, "delete", return_value=Mock(ok=True)) as delete:
        assert whatsapp.apagar_para_todos("jid", "ID") is True
    assert delete.call_args.args[0] == "http://evolution:8080/chat/deleteMessageForEveryone/central"
    assert delete.call_args.kwargs["json"] == {"id": "ID", "remoteJid": "jid", "fromMe": True}


def test_sem_chave_apagar_continua_recusando():
    with patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos("jid", "ID") is False
    assert delete.call_count == 0
