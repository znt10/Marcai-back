from unittest.mock import patch

from app.tasks import lembretes, whatsapp_healthcheck, zelador
from backend.celery import app as celery_app


def test_lembretes_chama_enviar_pendentes():
    # Chamada direta: prova a funcao, nao o transporte.
    with patch("app.tasks.enviar_pendentes", return_value=3) as mock_enviar:
        assert lembretes() == 3
    mock_enviar.assert_called_once()


def test_whatsapp_healthcheck_devolve_o_estado():
    with patch("app.tasks.estado_da_instancia", return_value="open"):
        assert whatsapp_healthcheck() == "open"


def test_whatsapp_healthcheck_loga_quando_nao_esta_aberto(caplog):
    with patch("app.tasks.estado_da_instancia", return_value="close"):
        with caplog.at_level("WARNING"):
            resultado = whatsapp_healthcheck()
    assert resultado == "close"
    assert "FORA DO AR" in caplog.text


def test_zelador_chama_alarmar_e_podar():
    esperado = {"recusados": 0, "podados_message_update": 0, "podados_message": 0}
    with patch("app.tasks.alarmar_e_podar", return_value=esperado) as mock_zelar:
        assert zelador() == esperado
    mock_zelar.assert_called_once()


def test_as_tres_tarefas_estao_registradas_no_app():
    # Sem isto, seriam funcoes comuns que ninguem consegue enfileirar — e o
    # sintoma no worker e' silencio, nao erro. O import no topo do arquivo e'
    # o que garante o registro (o decorator `@shared_task` roda na IMPORTACAO
    # do modulo) independente de quando/se o `autodiscover_tasks()` lazy do
    # `backend/celery.py` dispara — mesma garantia que o teste do `ping`
    # tinha antes desta fatia.
    assert "app.tasks.lembretes" in celery_app.tasks
    assert "app.tasks.whatsapp_healthcheck" in celery_app.tasks
    assert "app.tasks.zelador" in celery_app.tasks


def test_o_beat_tem_as_tres_na_agenda():
    from django.conf import settings

    agenda = settings.CELERY_BEAT_SCHEDULE
    assert agenda["lembretes"]["task"] == "app.tasks.lembretes"
    assert agenda["whatsapp-healthcheck"]["task"] == "app.tasks.whatsapp_healthcheck"
    assert agenda["zelador"]["task"] == "app.tasks.zelador"
    # O tique espelha o `sleep` que cada `while true` tinha: 600s pros dois
    # que giravam a cada 10 min, 3600s pro zelador (girava de hora em hora).
    assert agenda["lembretes"]["schedule"] == 600.0
    assert agenda["whatsapp-healthcheck"]["schedule"] == 600.0
    assert agenda["zelador"]["schedule"] == 3600.0


def test_ping_nao_existe_mais():
    # tenant/tasks.py foi apagado nesta fatia — o proprio docstring do ping
    # ja anunciava isso.
    import importlib

    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("tenant.tasks")
