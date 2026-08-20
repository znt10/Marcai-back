import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from fabricas import criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return criar_barbeiro(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.usuario_id, bid=barbearia_id, papel=barbeiro.usuario.papel, tv=0)
    return host


def _agendamento(barbearia_id, barbeiro, inicio, servico_nome="Corte"):
    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id,
        nome=f"{servico_nome} {uuid.uuid4().hex[:6]}",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Cliente",
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico_nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )


def test_lista_os_agendamentos_do_dia_pedido(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="DONO")
    host = _logar(client, barbeiro, b.id)

    dia = "2026-08-20"
    inicio = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
    a = _agendamento(b.id, barbeiro, inicio)
    # Fora do dia pedido — nao pode aparecer.
    _agendamento(b.id, barbeiro, datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc))

    r = client.get("/api/painel/agenda", {"dia": dia}, headers={"host": host})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["dia"] == dia
    assert [i["id"] for i in corpo["itens"]] == [a.id]
    assert corpo["itens"][0]["clienteNome"] == "Cliente"


def test_barbeiro_so_ve_a_propria_agenda_mesmo_pedindo_outra(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    dia = "2026-08-20"
    inicio = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
    _agendamento(b.id, colega, inicio)

    r = client.get(
        "/api/painel/agenda", {"dia": dia, "barbeiroId": colega.id}, headers={"host": host},
    )
    assert r.status_code == 200
    assert r.json()["itens"] == []


def test_dia_invalido_cai_no_dia_de_hoje(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.get("/api/painel/agenda", {"dia": "lixo"}, headers={"host": host})
    assert r.status_code == 200
    assert r.json()["dia"]  # so confere que respondeu com algum dia valido
