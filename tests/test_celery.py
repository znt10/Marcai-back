from backend.celery import app as celery_app
from tenant.tasks import ping


def test_ping_devolve_pong():
    # Chamada direta: prova a funcao, nao o transporte.
    assert ping() == "pong"


def test_a_tarefa_esta_registrada_no_app():
    # Sem isto, `ping` seria uma funcao comum que ninguem consegue enfileirar —
    # e o sintoma no worker e silencio, nao erro.
    assert "tenant.tasks.ping" in celery_app.tasks


def test_o_beat_tem_o_ping_na_agenda():
    from django.conf import settings

    agenda = settings.CELERY_BEAT_SCHEDULE
    assert "ping" in agenda
    assert agenda["ping"]["task"] == "tenant.tasks.ping"
