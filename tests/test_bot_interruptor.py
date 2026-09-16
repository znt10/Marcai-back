"""POST /api/painel/whatsapp/bot — ligar e desligar o atendimento automatico.

Duas regras: so' o DONO liga (um barbeiro mudaria como todo cliente e'
atendido, sem o dono saber), e o interruptor nunca mente — a Evolution aceita
primeiro, o banco grava depois.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import Barbearia, Barbeiro, EstadoInstancia, WhatsappInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/painel/whatsapp/bot"
ASSINAR = "app.services.whatsapp_painel.aplicar_assinatura"


def _barbeiro(barbearia, papel):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=f"{papel} teste",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia):
    from app.services.sessao import COOKIE_SESSAO, emitir

    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia.id, papel=barbeiro.papel, tv=barbeiro.token_version,
    )
    return f"{barbearia.slug}.localhost"


def _com_zap(barbearia, estado=EstadoInstancia.CONECTADO, **campos):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, **campos,
    )


def _bot_ativo(barbearia):
    return WhatsappInstancia.objects.using("owner").get(barbearia_id=barbearia.id).bot_ativo


def _post(client, host, corpo):
    return client.post(
        ROTA, corpo, content_type="application/json",
        headers={"host": host, "x-brutus-cliente": "web"},
    )


def test_dono_liga_e_a_evolution_e_avisada_antes(client, cenario):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=True) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "botAtivo": True}
    assinar.assert_called_once_with(nome_da_instancia(b.id), bot=True)
    assert _bot_ativo(b) is True


def test_dono_desliga(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, bot_ativo=True)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=True) as assinar:
        r = _post(client, host, {"ativo": False})
    assert r.status_code == 200
    assinar.assert_called_once_with(nome_da_instancia(b.id), bot=False)
    assert _bot_ativo(b) is False


def test_evolution_recusando_deixa_como_estava(client, cenario):
    """Ligado na tela e surdo na pratica e' o pior defeito possivel: o dono
    pararia de responder cliente achando que o robo responde."""
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=False):
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assert _bot_ativo(b) is False


def test_barbeiro_nao_liga(client, cenario):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "BARBEIRO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 403
    assinar.assert_not_called()
    assert _bot_ativo(b) is False


def test_sem_zap_nao_liga(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assinar.assert_not_called()


def test_instancia_pendente_nem_chama_a_evolution(client, cenario):
    """PENDENTE e' "a Evolution ainda nao sabe que isto existe": o `webhook/set`
    seria 404 de qualquer jeito."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.PENDENTE)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assinar.assert_not_called()


@pytest.mark.parametrize("corpo", [{}, {"ativo": "sim"}, {"ativo": 1}, {"ativo": None}])
def test_ativo_precisa_ser_booleano(client, cenario, corpo):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, corpo)
    assert r.status_code == 422
    assinar.assert_not_called()


def test_ver_mostra_o_interruptor_para_todo_mundo(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, bot_ativo=True)
    host = _logar(client, _barbeiro(b, "BARBEIRO"), b)
    r = client.get("/api/painel/whatsapp", headers={"host": host})
    assert r.json()["botAtivo"] is True


def test_ver_sem_zap_diz_desligado(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b, "DONO"), b)
    r = client.get("/api/painel/whatsapp", headers={"host": host})
    assert r.json()["botAtivo"] is False
