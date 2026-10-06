"""GET /api/painel/whatsapp (a saudacao com o link, etapa 1) e POST
/api/painel/whatsapp/desconectar."""

import uuid

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Barbearia,
    Barbeiro,
    EstadoInstancia,
    MensagemNaoEnviada,
    WhatsappInstancia,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/painel/whatsapp"


def _barbeiro(barbearia_id, papel="BARBEIRO"):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"{papel} teste",
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
    barbearia.plano = "COM_ZAP"
    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, **campos,
    )


def test_sem_sessao_da_401(client, cenario):
    r = client.get(ROTA, headers={"host": "brutus.localhost"})
    assert r.status_code == 401


def test_dono_desconecta(client, cenario):
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583999990000")
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    with patch("app.services.whatsapp_painel.desconectar_aparelho", return_value=True) as sair:
        r = client.post(
            f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"},
        )
    assert r.status_code == 200
    assert sair.call_count == 1


def test_barbeiro_nao_desconecta(client, cenario):
    """403 e nao 404: quem chegou aqui tem sessao valida e ja sabe que nao e
    dono — esconder a rota nao esconderia nada que ele nao soubesse."""
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)
    host = _logar(client, _barbeiro(b.id), b)

    with patch("app.services.whatsapp_painel.desconectar_aparelho") as sair:
        r = client.post(
            f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"},
        )
    assert r.status_code == 403
    assert sair.call_count == 0


def test_desconectar_sem_zap_da_422(client, cenario):
    """Nao ha aparelho para desligar. 422 e nao 404: a rota existe, o pedido e
    que nao faz sentido nesse plano."""
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    r = client.post(f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"})
    assert r.status_code == 422


SAUDACAO = (
    "Oi! Pra marcar seu horário, é só tocar no link: https://brutus.usemarcai.online\n"
    "Se preferir, espera uns minutinhos que já vamos te responder."
)


@pytest.fixture(autouse=True)
def _url_base(monkeypatch):
    monkeypatch.setenv("URL_BASE", "https://usemarcai.online")


@pytest.mark.parametrize("papel", ["DONO", "BARBEIRO"])
def test_todo_barbeiro_ve_a_saudacao_com_o_link_da_barbearia(client, cenario, papel):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, papel), b)
    assert client.get(ROTA, headers={"host": host}).json() == {
        "saudacao": SAUDACAO, "naoEnviadas": 0,
    }


def test_conta_as_mensagens_que_nao_sairam(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)
    for nome in ("Ana", "Bia"):
        MensagemNaoEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, tipo="CONFIRMACAO", cliente_nome=nome,
        )
    assert client.get(ROTA, headers={"host": host}).json()["naoEnviadas"] == 2


def test_nao_ve_as_nao_enviadas_da_outra(client, cenario):
    outra = cenario["dontony"]
    MensagemNaoEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=outra.id, tipo="CONFIRMACAO", cliente_nome="De la",
    )
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)
    assert client.get(ROTA, headers={"host": host}).json()["naoEnviadas"] == 0
