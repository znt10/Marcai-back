import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from tenant.datas import dia_de_hoje, dia_semana_de, local_para_utc, somar_dias, utc_para_local


def _dia_semana(momento):
    """O dia da semana que o MOTOR procura para este instante.

    A explicacao inteira esta em `tests/test_agendamentos.py`.
    """
    dia, _ = utc_para_local(momento)
    return dia_semana_de(dia)


pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0)
    return host


def _agendamento_futuro(barbearia_id, barbeiro, inicio):
    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Cliente",
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )


def test_agendamento_fora_da_jornada_e_conflito(client, cenario):
    """Sem HorarioTrabalho nenhum nesse dia da semana — o dia foi fechado
    depois do agendamento ter sido feito."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    a = _agendamento_futuro(b.id, barbeiro, futuro)

    r = client.get("/api/painel/conflitos", {"barbeiroId": barbeiro.id}, headers={"host": host})
    assert r.status_code == 200
    assert [c["id"] for c in r.json()["conflitos"]] == [a.id]


def test_agendamento_dentro_da_jornada_sem_bloqueio_nao_e_conflito(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    # Meio-dia, e nao `agora + 2 dias`: rodando depois das 23:30 o corte de
    # 30 minutos virava a meia-noite e saia da jornada 0-1440 — conflito de
    # verdade, e o teste falhava so' nesse meio hora.
    futuro = local_para_utc(somar_dias(dia_de_hoje(datetime.now(timezone.utc)), 2), 720)
    from tenant.models import HorarioTrabalho

    dia_semana = _dia_semana(futuro)
    HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
        dia_semana=dia_semana, minutos_inicio=0, minutos_fim=1440,
    )
    _agendamento_futuro(b.id, barbeiro, futuro)

    r = client.get("/api/painel/conflitos", {"barbeiroId": barbeiro.id}, headers={"host": host})
    assert r.json()["conflitos"] == []


def test_barbeiro_pedindo_conflito_do_colega_e_404(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    r = client.get("/api/painel/conflitos", {"barbeiroId": colega.id}, headers={"host": host})
    assert r.status_code == 404


def test_agendamento_aguardando_pagamento_tambem_e_conflito(client, cenario):
    """Uma folga nao pode passar por cima de horario esperando o Pix."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    a = _agendamento_futuro(b.id, barbeiro, futuro)
    from tenant.models import Agendamento

    Agendamento.objects.using("owner").filter(id=a.id).update(status="AGUARDANDO_PAGAMENTO")

    r = client.get("/api/painel/conflitos", {"barbeiroId": barbeiro.id}, headers={"host": host})
    assert [c["id"] for c in r.json()["conflitos"]] == [a.id]
