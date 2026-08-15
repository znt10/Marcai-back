import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

HOST = "admin.localhost"


def _cabecalho(segredo="segredo-do-cron"):
    return {
        "host": HOST, "authorization": f"Bearer {segredo}", "x-brutus-cliente": "cron",
    }


def _barbeiro(barbearia_id, nome="Zeca"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel="BARBEIRO", ativo=True,
    )


def _agendamento(
    barbearia_id, barbeiro, inicio, status="CONFIRMADO", lembrete_enviado_em=None,
):
    from tenant.models import Agendamento, Cliente, Servico

    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Cliente",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
    )
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Corte",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status, lembrete_enviado_em=lembrete_enviado_em,
    )


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


@pytest.fixture(autouse=True)
def _com_cron_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "segredo-do-cron")


# ------------------------------------------------------------------- acesso


def test_sem_cron_secret_no_ambiente_nega_tudo(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    r = client.post(
        "/api/cron/lembretes",
        headers={
            "host": HOST, "authorization": "Bearer qualquer", "x-brutus-cliente": "cron",
        },
    )
    assert r.status_code == 401


def test_bearer_errado_da_401(client):
    r = client.post("/api/cron/lembretes", headers=_cabecalho(segredo="errado"))
    assert r.status_code == 401


def test_sem_x_brutus_cliente_da_403(client):
    """Achado #10 do card Travessia: sem este header o `ClienteMiddleware`
    recusa ANTES da view — e' por isso que o `agendador` (docker-compose)
    precisa manda-lo no mesmo commit que criou esta rota."""
    r = client.post(
        "/api/cron/lembretes", headers={"host": HOST, "authorization": "Bearer segredo-do-cron"},
    )
    assert r.status_code == 403


def test_sem_cabecalho_authorization_da_401(client):
    r = client.post(
        "/api/cron/lembretes", headers={"host": HOST, "x-brutus-cliente": "cron"},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------- envio


def test_envia_e_marca_o_pendente_dentro_da_janela(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    a = _agendamento(b.id, barbeiro, inicio)

    with patch("app.services.lembrete.enviar_texto") as mock_envia:
        r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.status_code == 200
    assert r.json() == {"enviados": 1}
    mock_envia.assert_called_once()

    from tenant.models import Agendamento

    atualizado = Agendamento.objects.using("owner").get(id=a.id)
    assert atualizado.lembrete_enviado_em is not None


def test_nao_manda_de_novo_o_ja_avisado(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    _agendamento(b.id, barbeiro, inicio, lembrete_enviado_em=datetime.now(timezone.utc))

    with patch("app.services.lembrete.enviar_texto") as mock_envia:
        r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.status_code == 200
    assert r.json() == {"enviados": 0}
    mock_envia.assert_not_called()


def test_fora_da_janela_nao_e_pego(client, cenario):
    """Alem de 60 min (LEMBRETE_ANTECEDENCIA_MIN): o proximo tique pega."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=2)
    _agendamento(b.id, barbeiro, inicio)

    with patch("app.services.lembrete.enviar_texto") as mock_envia:
        r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.json() == {"enviados": 0}
    mock_envia.assert_not_called()


def test_horario_ja_passado_nao_e_pego(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) - timedelta(minutes=5)
    _agendamento(b.id, barbeiro, inicio)

    r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.json() == {"enviados": 0}


def test_status_diferente_de_confirmado_nao_e_pego(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    _agendamento(b.id, barbeiro, inicio, status="CANCELADO_CLIENTE")

    r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.json() == {"enviados": 0}


def test_barbearia_inativa_e_ignorada(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    _agendamento(b.id, barbeiro, inicio)

    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(id=b.id).update(ativo=False)

    r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.json() == {"enviados": 0}


def test_isola_por_barbearia_e_soma_o_total(client, cenario):
    b1, b2 = cenario["brutus"], cenario["dontony"]
    barbeiro1, barbeiro2 = _barbeiro(b1.id), _barbeiro(b2.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    _agendamento(b1.id, barbeiro1, inicio)
    _agendamento(b2.id, barbeiro2, inicio)

    with patch("app.services.lembrete.enviar_texto") as mock_envia:
        r = client.post("/api/cron/lembretes", headers=_cabecalho())
    assert r.json() == {"enviados": 2}
    assert mock_envia.call_count == 2
