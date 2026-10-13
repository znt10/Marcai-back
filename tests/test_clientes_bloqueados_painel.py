import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from test_clientes_bloqueados import _agendamento, _barbeiro, _cliente

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _h():
    return {"host": HOST, **CABECALHO}


def test_previa_e_bloquear_pela_agenda(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)
    maria = _cliente(b.id)
    futuro = datetime.now(timezone.utc) + timedelta(days=1)
    a = _agendamento(b.id, zeca, maria, futuro)

    r = client.get(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())
    assert r.status_code == 200
    assert r.json()["horarios"] == 1 and r.json()["nome"] == "Maria"

    with patch("app.services.lista_do_dia.avisar_mudanca") as avisar, patch(
        "app.services.whatsapp.enviar_ao_cliente"
    ) as ao_cliente:
        r = client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())
    assert r.status_code == 200
    assert r.json() == {"ok": True, "cancelados": 1}
    ao_cliente.assert_not_called()
    args, kwargs = avisar.call_args
    assert str(args[1]) == str(zeca.id)
    assert [str(i) for i, _ in kwargs["cancelados"]] == [str(a.id)]


def test_bloquear_agendamento_do_colega_e_404(client, cenario):
    b = cenario["brutus"]
    eu, colega = _barbeiro(b.id, "Eu"), _barbeiro(b.id, "Colega")
    _logar(client, eu, b.id)
    a = _agendamento(b.id, colega, _cliente(b.id), datetime.now(timezone.utc) + timedelta(days=1))

    assert client.get(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h()).status_code == 404
    assert client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h()).status_code == 404


def test_bloquear_id_inexistente_ou_torto_e_404(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)

    for id_ in (str(uuid.uuid4()), "nao-existe"):
        r = client.post(f"/api/painel/agendamentos/{id_}/bloquear-cliente", headers=_h())
        assert r.status_code == 404


def test_dono_lista_e_desbloqueia(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    _logar(client, dono, b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, dono, maria, datetime.now(timezone.utc) + timedelta(days=1))
    with patch("app.services.lista_do_dia.avisar_mudanca"):
        client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())

    r = client.get("/api/painel/clientes/bloqueados", headers=_h())
    assert r.status_code == 200
    assert [c["nome"] for c in r.json()] == ["Maria"]

    r = client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h())
    assert r.status_code == 200
    assert client.get("/api/painel/clientes/bloqueados", headers=_h()).json() == []

    r = client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h())
    assert r.status_code == 404


def test_barbeiro_comum_nao_lista_nem_desbloqueia(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)
    maria = _cliente(b.id)

    r = client.get("/api/painel/clientes/bloqueados", headers=_h())
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono vê os clientes bloqueados."
    assert client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h()).status_code == 403
