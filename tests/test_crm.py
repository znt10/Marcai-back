from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import requests
from django.test import override_settings

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

BRASILIA = ZoneInfo("America/Sao_Paulo")
CRM = dict(
    CRM_WEBHOOK_URL="https://crm.teste/api/webhooks/recebimento?project=marcai",
    CRM_WEBHOOK_SEGREDO="s3gredo",
    PIX_CHAVE="Dono@Marcai.com",
    PIX_NOME_RECEBEDOR="Marcai",
    PIX_CIDADE="Patos",
)


def momento(ano, mes, dia, hora=12):
    return datetime(ano, mes, dia, hora, tzinfo=BRASILIA)


class _Resposta:
    def __init__(self, status=200):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = ""


@pytest.fixture
def b(cenario):
    from tenant.models import Assinatura

    Assinatura.objects.using("admin").filter(barbearia_id=cenario["brutus"].id).update(
        isenta=False, valor_centavos=10000, paga_ate=date(2026, 10, 10), dia_de_vencimento=10,
    )
    return cenario["brutus"].id


@pytest.fixture
def agendados(monkeypatch):
    """O `delay` da tarefa vira uma lista: o que o commit agendou."""
    from app import tasks

    feitos = []
    monkeypatch.setattr(tasks.avisar_crm, "delay", lambda *a: feitos.append(a))
    return feitos


class _Posts(list):
    falso = None


@pytest.fixture
def posts(monkeypatch):
    feitos = _Posts()

    def falso(url, json=None, headers=None, timeout=None):
        feitos.append({"url": url, "json": json, "headers": headers})
        return falso.resposta

    falso.resposta = _Resposta()
    monkeypatch.setattr(requests, "post", falso)
    feitos.falso = falso
    return feitos


def test_sem_configurar_nada_e_agendado(b, agendados):
    from app.services.mensalidade import operacoes

    with override_settings(CRM_WEBHOOK_URL="", CRM_WEBHOOK_SEGREDO="", PIX_CHAVE="a@b.com",
                           PIX_NOME_RECEBEDOR="M", PIX_CIDADE="P"):
        c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
        operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 13))
    assert agendados == []


@override_settings(**CRM)
def test_confirmar_agenda_o_aviso_de_pago(b, agendados):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 13), como="VIGIA")
    assert agendados == [(str(c.id), "pago")]


@override_settings(**CRM)
def test_registrar_e_remover_agendam_os_dois_avisos(b, agendados):
    from app.services import admin_mensalidades
    from app.services.mensalidade import operacoes

    c = operacoes.registrar_manual(b, valor_centavos=10000, agora=momento(2026, 10, 12))
    admin_mensalidades.remover_pagamento(c.id, agora=momento(2026, 10, 13))
    assert agendados == [(str(c.id), "pago"), (str(c.id), "removido")]


@override_settings(**CRM)
def test_confirmacao_desfeita_nao_avisa(b, agendados):
    from django.db import transaction

    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    with pytest.raises(RuntimeError), transaction.atomic(using="admin"):
        operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 13))
        raise RuntimeError
    assert agendados == []


@override_settings(**CRM)
def test_enviar_manda_o_pagamento_com_o_segredo(b, posts):
    from app.services import crm
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 13), como="INFINITEPAY")
    crm.enviar(str(c.id), crm.PAGO)

    (post,) = posts
    assert post["url"] == CRM["CRM_WEBHOOK_URL"]
    assert post["headers"] == {"X-CRM-Segredo": "s3gredo"}
    assert post["json"]["acao"] == "pago"
    assert post["json"]["external_id"] == str(c.id)
    assert post["json"]["valor_centavos"] == c.valor_centavos
    assert post["json"]["meio"] == "infinitepay"
    assert post["json"]["descricao"].startswith("Mensalidade · ")


@override_settings(**CRM)
def test_crm_fora_do_ar_levanta_para_a_tarefa_tentar_de_novo(b, posts):
    from app.services import crm
    from app.services.mensalidade import operacoes

    c = operacoes.registrar_manual(b, valor_centavos=10000, agora=momento(2026, 10, 12))
    posts.falso.resposta = _Resposta(503)
    with pytest.raises(crm.ErroDoCrm):
        crm.enviar(str(c.id), crm.PAGO)
