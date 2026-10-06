"""Quem fala com quem, por qual numero — etapa 1 do numero central.

A regra inteira: **tudo sai pelo numero central do Marcai**, equipe e
cliente. O numero da barbearia saiu da Evolution (spec 2026-10-06): um
bloqueio do WhatsApp agora derruba o numero do Marcai, que o Jose troca, e
nunca o do negocio do cliente.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
import requests

from app.services import whatsapp
from tenant.models import (
    Barbearia,
    EstadoInstancia,
    MensagemNaoEnviada,
    TipoMensagem,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "central-do-marcai")
    whatsapp.limpar_caches_numero()


def _com_zap(barbearia):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    barbearia.plano = "COM_ZAP"
    return barbearia


def _instancia_velha(barbearia):
    """Uma linha de instancia CONECTADA que sobrou de antes do comando que
    desliga tudo. Ela nao pode mais decidir por onde a mensagem sai."""
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=f"marcai-{barbearia.id}", estado=EstadoInstancia.CONECTADO,
    )


def _nao_enviadas(barbearia):
    with com_barbearia(barbearia.id):
        return list(MensagemNaoEnviada.objects.all())


def _instancia_usada(chamada):
    """A URL termina no nome da instancia: e' ela que diz de qual numero
    saiu."""
    return chamada.call_args.args[0].rsplit("/", 1)[-1]


def _ok():
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0X", "remoteJid": "5511977778888@s.whatsapp.net"},
        "status": "PENDING",
    }
    return resposta


def _para_o_cliente(barbearia, **kw):
    return whatsapp.enviar_ao_cliente(
        barbearia, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO,
        cliente_nome=kw.get("cliente_nome", "Ana"),
    )


# ---- cliente ----


def test_cliente_com_zap_recebe_pelo_central(cenario):
    b = _com_zap(cenario["brutus"])
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        assert _para_o_cliente(b) is True
    assert _instancia_usada(post) == "central-do-marcai"
    assert _nao_enviadas(b) == []


def test_instancia_velha_da_barbearia_nao_desvia_o_cliente(cenario):
    b = _com_zap(cenario["brutus"])
    _instancia_velha(b)
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        assert _para_o_cliente(b) is True
    assert _instancia_usada(post) == "central-do-marcai"


def test_sem_zap_nao_manda_e_nao_registra(cenario):
    b = cenario["brutus"]
    with patch.object(whatsapp.requests, "post") as post:
        assert _para_o_cliente(b) is False
    assert post.call_count == 0
    assert _nao_enviadas(b) == []


@pytest.mark.parametrize("status, texto", [(400, "desconectado"), (401, "Unauthorized")])
def test_central_recusando_registra_nao_enviada(cenario, status, texto):
    b = _com_zap(cenario["brutus"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=status, text=texto)
    ):
        assert _para_o_cliente(b) is False
    registradas = _nao_enviadas(b)
    assert len(registradas) == 1
    assert registradas[0].tipo == TipoMensagem.CONFIRMACAO
    assert registradas[0].cliente_nome == "Ana"


def test_central_fora_da_rede_registra_nao_enviada(cenario):
    b = _com_zap(cenario["brutus"])
    with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("x")):
        assert _para_o_cliente(b) is False
    assert len(_nao_enviadas(b)) == 1


def test_sem_url_nao_registra(cenario, monkeypatch):
    """Desenvolvimento: nao houve queda, so' nao ha servidor."""
    monkeypatch.delenv("EVOLUTION_API_URL")
    b = _com_zap(cenario["brutus"])
    assert _para_o_cliente(b) is False
    assert _nao_enviadas(b) == []


def test_registro_falhando_nao_derruba_quem_chamou(cenario, caplog):
    b = _com_zap(cenario["brutus"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")
    ), patch.object(
        whatsapp.MensagemNaoEnviada.objects, "create", side_effect=RuntimeError("boom")
    ):
        with caplog.at_level("ERROR"):
            assert _para_o_cliente(b) is False
    assert "nao enviada" in caplog.text


def test_a_nao_enviada_fica_na_barbearia_certa(cenario):
    b = _com_zap(cenario["brutus"])
    outra = _com_zap(cenario["dontony"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")
    ):
        _para_o_cliente(b, cliente_nome="Da Brutus")
    assert [m.cliente_nome for m in _nao_enviadas(b)] == ["Da Brutus"]
    assert _nao_enviadas(outra) == []


# ---- equipe ----


def test_equipe_da_barbearia_sai_pelo_central_mesmo_com_instancia_conectada(cenario):
    b = _com_zap(cenario["brutus"])
    _instancia_velha(b)
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe_da(b.id, "11911112222", "Novo horário")
    assert _instancia_usada(post) == "central-do-marcai"


def test_equipe_sem_zap_tambem_recebe(cenario):
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe_da(cenario["brutus"].id, "11911112222", "Novo horário")
    assert post.call_count == 1


# ---- a checagem do numero ----


def test_sem_zap_nao_pergunta_se_o_numero_tem_whatsapp(cenario):
    with patch.object(whatsapp.requests, "post") as post:
        assert whatsapp.numero_existe(cenario["brutus"], "11977778888", "1.1.1.1") == "indeterminado"
    assert post.call_count == 0


def test_com_zap_pergunta_pelo_central_mesmo_sem_instancia_da_barbearia(cenario):
    b = _com_zap(cenario["brutus"])
    resposta = _ok()
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.numero_existe(b, "11977778888", "1.1.1.1") == "existe"
    assert _instancia_usada(post) == "central-do-marcai"
