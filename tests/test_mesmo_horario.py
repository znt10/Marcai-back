"""Duas pessoas marcando o MESMO horario do MESMO barbeiro ao mesmo tempo.

Quem garante e' o banco: `agendamento_sem_sobreposicao` (0003) recusa o
segundo INSERT que cruza o intervalo de outro CONFIRMADO do mesmo barbeiro,
mesmo com os dois pedidos passando juntos pela checagem de vaga. O segundo
recebe 409 com a frase que o site mostra, e so' o primeiro e' confirmado.

Aqui os dois pedidos saem de verdade em paralelo (duas threads, duas conexoes
com o banco, soltas juntas por uma barreira) — e nao um depois do outro, que
provaria so' a checagem de vaga.
"""
import threading
from datetime import datetime, timezone

import pytest
from django.db import connections
from django.test import Client

from tenant.datas import dia_de_hoje, dia_semana_de, local_para_utc, somar_dias

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def _barbeiro_com_dia_aberto(barbearia, nome, numero, dia):
    from tenant.models import Barbeiro, BarbeiroServico, HorarioTrabalho, Servico

    servico = Servico.objects.using("owner").get_or_create(
        barbearia_id=barbearia.id, nome="Corte",
        defaults={"duracao_minima_min": 10, "duracao_sugerida_min": 30},
    )[0]
    barbeiro = Barbeiro.objects.using("owner").create(
        barbearia_id=barbearia.id, nome=nome, whatsapp=numero, ativo=True,
    )
    BarbeiroServico.objects.using("owner").create(
        barbearia_id=barbearia.id, barbeiro=barbeiro, servico=servico, duracao_min=30,
    )
    HorarioTrabalho.objects.using("owner").create(
        barbearia_id=barbearia.id, barbeiro=barbeiro, dia_semana=dia_semana_de(dia),
        minutos_inicio=0, minutos_fim=1440,
    )
    return barbeiro, servico


def _ao_mesmo_tempo(pedidos):
    """Solta todos os pedidos juntos e devolve as respostas na mesma ordem."""
    barreira = threading.Barrier(len(pedidos))
    respostas = [None] * len(pedidos)

    def rodar(i, corpo):
        try:
            barreira.wait()
            respostas[i] = Client().post(
                "/api/agendamentos", corpo, content_type="application/json",
                headers={"host": "brutus.localhost", **CABECALHO},
            )
        finally:
            connections.close_all()

    threads = [threading.Thread(target=rodar, args=(i, c)) for i, c in enumerate(pedidos)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return respostas


def _pedido(barbeiro, servico, inicio, nome, numero):
    return {"barbeiroId": str(barbeiro.id), "servicoId": str(servico.id),
            "inicio": inicio.isoformat(), "nome": nome, "whatsapp": numero}


@pytest.mark.parametrize("rodada", range(5))
def test_mesmo_barbeiro_mesmo_horario_so_o_primeiro_fica(cenario, rodada):
    from tenant.models import Agendamento

    dia = somar_dias(dia_de_hoje(datetime.now(timezone.utc)), 2)
    inicio = local_para_utc(dia, 15 * 60)
    zeca, corte = _barbeiro_com_dia_aberto(cenario["brutus"], "Zeca", "83911110001", dia)

    r1, r2 = _ao_mesmo_tempo([
        _pedido(zeca, corte, inicio, "Maria Teste", "83933330003"),
        _pedido(zeca, corte, inicio, "Joao Teste", "83944440004"),
    ])

    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    perdeu = r1 if r1.status_code == 409 else r2
    assert perdeu.json()["erro"] == "Esse horário acabou de ser pego. Escolhe outro?"
    assert Agendamento.objects.using("owner").filter(
        barbeiro_id=zeca.id, inicio=inicio, status="CONFIRMADO",
    ).count() == 1


def test_mesmo_horario_em_barbeiros_diferentes_os_dois_ficam(cenario):
    dia = somar_dias(dia_de_hoje(datetime.now(timezone.utc)), 2)
    inicio = local_para_utc(dia, 15 * 60)
    zeca, corte = _barbeiro_com_dia_aberto(cenario["brutus"], "Zeca", "83911110001", dia)
    rael, _ = _barbeiro_com_dia_aberto(cenario["brutus"], "Rael", "83922220002", dia)

    r1, r2 = _ao_mesmo_tempo([
        _pedido(zeca, corte, inicio, "Maria Teste", "83933330003"),
        _pedido(rael, corte, inicio, "Joao Teste", "83944440004"),
    ])

    assert (r1.status_code, r2.status_code) == (201, 201)
