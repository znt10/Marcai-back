"""Os avisos da mensalidade pelo zap. Cada nivel (vencendo, vence hoje,
bloqueada) sai uma vez por `paga_ate`; confirmar/recusar avisam o dono depois
do commit; o "ja paguei" avisa o Jose so' se o numero dele estiver configurado."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

BRASILIA = ZoneInfo("America/Sao_Paulo")
ENVIO = "app.services.mensalidade.avisos.enviar_a_equipe"
ENVIO_OPS = "app.services.mensalidade.operacoes.enviar_a_equipe"
PIX = {"PIX_CHAVE": "dono@marcai.com", "PIX_NOME_RECEBEDOR": "Marcai", "PIX_CIDADE": "Patos"}


def momento(ano, mes, dia, hora=9):
    return datetime(ano, mes, dia, hora, 0, tzinfo=BRASILIA)


@pytest.fixture(autouse=True)
def _pix():
    with override_settings(**PIX):
        yield


def _paga(barbearia_id, *, valor=4990, paga_ate=date(2026, 10, 10), **extra):
    from tenant.models import Assinatura

    campos = {"isenta": False, **extra}
    Assinatura.objects.using("admin").filter(barbearia_id=barbearia_id).update(
        valor_centavos=valor, paga_ate=paga_ate, dia_de_vencimento=paga_ate.day, **campos,
    )


@pytest.fixture
def b(cenario):
    from tenant.models import Barbeiro

    _paga(cenario["brutus"].id)
    # O cenario cria um barbeiro so'; ele vira o dono.
    Barbeiro.objects.using("owner").filter(barbearia_id=cenario["brutus"].id).update(papel="DONO")
    return cenario["brutus"].id


@pytest.fixture
def dono(b):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").get(barbearia_id=b)


def _rodar(agora):
    from app.services.mensalidade import avisos

    with patch(ENVIO) as envio:
        n = avisos.enviar_do_dia(agora=agora)
    return n, envio


# --- a tarefa diaria ---

def test_vencendo_sai_uma_vez_em_duas_rodadas(b, dono):
    n1, e1 = _rodar(momento(2026, 10, 5))
    n2, e2 = _rodar(momento(2026, 10, 5))
    assert (n1, n2) == (1, 0)
    e1.assert_called_once()
    assert e1.call_args.args[0] == dono.whatsapp
    assert "R$ 49,90" in e1.call_args.args[1]
    e2.assert_not_called()


def test_vencendo_no_dia_seguinte_nao_repete(b):
    _rodar(momento(2026, 10, 5))
    n, envio = _rodar(momento(2026, 10, 6))
    assert n == 0
    envio.assert_not_called()


def test_escala_vencendo_vence_hoje_bloqueada(b):
    _, e = _rodar(momento(2026, 10, 7))
    assert "3 dias" in e.call_args.args[1]
    _, e = _rodar(momento(2026, 10, 10))
    e.assert_called_once()
    assert "hoje" in e.call_args.args[1]
    # Dentro da tolerancia (atrasada) nao avisa.
    _, e = _rodar(momento(2026, 10, 12))
    e.assert_not_called()
    # Bloqueia em 16/10 (10 + 5 de carencia + 1).
    _, e = _rodar(momento(2026, 10, 16))
    e.assert_called_once()
    assert "site" in e.call_args.args[1]
    _, e = _rodar(momento(2026, 10, 17))
    e.assert_not_called()


def test_pulou_o_vencendo_manda_so_o_nivel_de_hoje(b):
    n, e = _rodar(momento(2026, 10, 10))
    assert n == 1
    e.assert_called_once()
    assert "hoje" in e.call_args.args[1]
    # E o vencendo de ontem nao sai atrasado depois.
    _, e = _rodar(momento(2026, 10, 10, 10))
    e.assert_not_called()


def test_novo_paga_ate_zera_o_registro(b):
    _rodar(momento(2026, 10, 10))
    _paga(b, paga_ate=date(2026, 11, 10))
    _, e = _rodar(momento(2026, 11, 5))
    e.assert_called_once()
    assert "10/11" in e.call_args.args[1]


def test_grava_o_ultimo_aviso(b):
    from tenant.models import Assinatura

    _rodar(momento(2026, 10, 10))
    a = Assinatura.objects.using("admin").get(barbearia_id=b)
    assert a.ultimo_aviso == "VENCE_HOJE"
    assert a.ultimo_aviso_paga_ate == date(2026, 10, 10)


def test_em_dia_aguardando_e_atrasada_nao_recebem(b):
    _, e = _rodar(momento(2026, 9, 1))
    e.assert_not_called()
    _, e = _rodar(momento(2026, 10, 13))
    e.assert_not_called()


def test_isenta_valor_zero_e_inativa_nao_recebem(b):
    from tenant.models import Barbearia

    _paga(b, isenta=True)
    _, e = _rodar(momento(2026, 10, 10))
    e.assert_not_called()
    _paga(b, isenta=False, valor=0)
    _, e = _rodar(momento(2026, 10, 10))
    e.assert_not_called()
    _paga(b, valor=4990)
    Barbearia.objects.using("admin").filter(id=b).update(ativo=False)
    _, e = _rodar(momento(2026, 10, 10))
    e.assert_not_called()


def test_sem_dono_ativo_nao_manda_e_nao_marca(b, dono):
    from tenant.models import Assinatura, Barbeiro

    Barbeiro.objects.using("owner").filter(id=dono.id).update(ativo=False)
    n, e = _rodar(momento(2026, 10, 10))
    assert n == 0
    e.assert_not_called()
    assert Assinatura.objects.using("admin").get(barbearia_id=b).ultimo_aviso == ""


def test_a_tarefa_chama_o_servico():
    from app.tasks import avisos_da_mensalidade

    with patch("app.tasks.enviar_avisos_da_mensalidade", return_value=2) as s:
        assert avisos_da_mensalidade() == 2
    s.assert_called_once()


def test_agenda_no_beat_as_9h():
    from django.conf import settings

    item = settings.CELERY_BEAT_SCHEDULE["avisos-da-mensalidade"]
    assert item["task"] == "app.tasks.avisos_da_mensalidade"
    assert (item["schedule"].hour, item["schedule"].minute) == ({9}, {0})


# --- as operacoes ---

def _com_cobranca(b, dono):
    from app.services.mensalidade import operacoes

    agora = momento(2026, 10, 11)
    operacoes.cobranca_do_ciclo(b, agora=agora)
    with patch(ENVIO_OPS):
        c = operacoes.informar_pagamento(b, dono.id, agora=agora)
    return c, agora


def test_confirmar_avisa_o_dono_com_a_nova_data(b, dono):
    from app.services.mensalidade import operacoes

    c, agora = _com_cobranca(b, dono)
    with patch(ENVIO_OPS) as envio:
        operacoes.confirmar(c.id, agora=agora)
    envio.assert_called_once()
    assert envio.call_args.args[0] == dono.whatsapp
    assert "10/11" in envio.call_args.args[1]


def test_recusar_avisa_o_dono(b, dono):
    from app.services.mensalidade import operacoes

    c, agora = _com_cobranca(b, dono)
    with patch(ENVIO_OPS) as envio:
        operacoes.recusar(c.id, agora=agora)
    envio.assert_called_once()
    assert envio.call_args.args[0] == dono.whatsapp


def test_aviso_so_sai_depois_do_commit(b, dono):
    from django.db import transaction

    from app.services.mensalidade import operacoes

    c, agora = _com_cobranca(b, dono)
    with patch(ENVIO_OPS) as envio:
        # Uma transacao de fora segura o commit: o aviso espera ela fechar.
        with transaction.atomic(using="admin"):
            operacoes.recusar(c.id, agora=agora)
            envio.assert_not_called()
        envio.assert_called_once()


def test_falha_do_envio_nao_desfaz_a_confirmacao(b, dono):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca, StatusCobranca

    c, agora = _com_cobranca(b, dono)
    with patch(ENVIO_OPS, side_effect=RuntimeError("zap fora")):
        operacoes.confirmar(c.id, agora=agora)
    assert Cobranca.objects.using("admin").get(id=c.id).status == StatusCobranca.PAGA


def test_informar_avisa_o_jose_quando_configurado(b, dono):
    from app.services.mensalidade import operacoes

    agora = momento(2026, 10, 11)
    with override_settings(MENSALIDADE_WHATSAPP_AVISO="11999990000"):
        with patch(ENVIO_OPS) as envio:
            operacoes.informar_pagamento(b, dono.id, agora=agora)
    envio.assert_called_once()
    assert envio.call_args.args[0] == "11999990000"
    assert "/mensalidades" in envio.call_args.args[1]


def test_informar_sem_numero_configurado_nao_manda(b, dono):
    from app.services.mensalidade import operacoes

    with override_settings(MENSALIDADE_WHATSAPP_AVISO=""):
        with patch(ENVIO_OPS) as envio:
            operacoes.informar_pagamento(b, dono.id, agora=momento(2026, 10, 11))
    envio.assert_not_called()


def test_registrar_manual_nao_manda_nada(b):
    from app.services.mensalidade import operacoes

    with patch(ENVIO_OPS) as envio:
        operacoes.registrar_manual(
            b, paga_ate=date(2026, 12, 10), valor_centavos=4990, agora=momento(2026, 10, 11),
        )
    envio.assert_not_called()


@pytest.mark.parametrize("config", [
    {"PIX_CHAVE": ""}, {"PIX_NOME_RECEBEDOR": ""}, {"PIX_CIDADE": ""},
])
def test_sem_pix_completo_nao_avisa(b, config):
    """Nao tranca (nao ha como pagar), entao tambem nao ameaca trancar."""
    for dia in (5, 10, 16):
        with override_settings(**config):
            n, e = _rodar(momento(2026, 10, dia))
        assert n == 0
        e.assert_not_called()
