"""GET /api/admin/whatsapp-central — o numero que carrega tudo desde a
etapa 1. O admin precisa ver se ele esta de pe e, quando nao estiver, ler o
QR com o chip do Marcai."""

from unittest.mock import Mock, patch

import pytest

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir
from tenant.models import EstadoInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

ROTA = "/api/admin/whatsapp-central"
CABECALHO = {"x-brutus-cliente": "web"}
HOST = "admin.localhost"
SERVICO = "app.services.whatsapp_central"


@pytest.fixture(autouse=True)
def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "Marcai")


def _get(client):
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()
    return client.get(ROTA, headers={"host": HOST, **CABECALHO})


def test_sem_cookie_da_401(client):
    assert client.get(ROTA, headers={"host": HOST, **CABECALHO}).status_code == 401


def test_conectado_mostra_o_numero_e_nao_pede_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.CONECTADO), patch(
        f"{SERVICO}.consultar_dono", return_value="5583999990000@s.whatsapp.net"
    ), patch(f"{SERVICO}.pedir_qr") as pedir:
        corpo = _get(client).json()
    assert corpo == {
        "configurado": True, "conectado": True, "numero": "83999990000", "qrBase64": None,
    }
    pedir.assert_not_called()


def test_desconectado_traz_o_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.DESCONECTADO), patch(
        f"{SERVICO}.pedir_qr", return_value="data:image/png;base64,AAA"
    ):
        corpo = _get(client).json()
    assert corpo == {
        "configurado": True, "conectado": False, "numero": None,
        "qrBase64": "data:image/png;base64,AAA",
    }


def test_instancia_inexistente_e_criada_e_traz_o_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.PENDENTE), patch(
        f"{SERVICO}.requests.post", return_value=Mock(ok=True, status_code=201)
    ) as post, patch(f"{SERVICO}.pedir_qr", return_value="data:image/png;base64,BBB"):
        corpo = _get(client).json()
    assert post.call_args.args[0] == "http://evolution:8080/instance/create"
    assert post.call_args.kwargs["json"]["instanceName"] == "Marcai"
    assert corpo["qrBase64"] == "data:image/png;base64,BBB"


def test_sem_evolution_configurada(client, monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL")
    assert _get(client).json() == {
        "configurado": False, "conectado": False, "numero": None, "qrBase64": None,
    }
