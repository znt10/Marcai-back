import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.clientes_bloqueados import (
    bloquear, desbloquear, esta_bloqueado, listar, previa,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

AGORA = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _cliente(barbearia_id, whatsapp="11977778888", nome="Maria"):
    from tenant.models import Cliente

    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome, whatsapp=whatsapp,
    )


def _agendamento(barbearia_id, barbeiro, cliente, inicio, status="CONFIRMADO", aparelho=None):
    from tenant.models import Agendamento, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico.nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status, aparelho=aparelho,
    )


def _status(agendamento):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").get(id=agendamento.id).status


# ------------------------------------------------------------ esta_bloqueado


def test_numero_livre_nao_esta_bloqueado(cenario):
    b = cenario["brutus"]
    _cliente(b.id)
    assert esta_bloqueado(b.id, "11977778888", None) is False


def test_numero_bloqueado_esta_bloqueado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    a = _agendamento(b.id, zeca, _cliente(b.id), AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)
    assert esta_bloqueado(b.id, "11977778888", None) is True


def test_numero_novo_no_aparelho_de_um_bloqueado_esta_bloqueado(cenario):
    """O aparelho marcou com o numero ANTES do bloqueio; depois ela troca de
    numero no mesmo celular."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=3), aparelho="cel-da-maria")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert esta_bloqueado(b.id, "11966665555", "cel-da-maria") is True
    assert esta_bloqueado(b.id, "11966665555", "outro-cel") is False
    assert esta_bloqueado(b.id, "11966665555", None) is False


def test_bloqueio_nao_vaza_para_outra_barbearia(cenario):
    b, d = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b.id)
    a = _agendamento(b.id, zeca, _cliente(b.id), AGORA + timedelta(days=1), aparelho="cel")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    _cliente(d.id)
    assert esta_bloqueado(d.id, "11977778888", "cel") is False


# ------------------------------------------------------------------ bloquear


def test_bloquear_cancela_so_os_futuros_confirmados_de_qualquer_barbeiro(cenario):
    b = cenario["brutus"]
    zeca, tuca = _barbeiro(b.id, "Zeca"), _barbeiro(b.id, "Tuca")
    maria = _cliente(b.id)
    origem = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    do_colega = _agendamento(b.id, tuca, maria, AGORA + timedelta(days=2))
    passado = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=1))
    ja_cancelado = _agendamento(
        b.id, zeca, maria, AGORA + timedelta(days=3), status="CANCELADO_CLIENTE",
    )

    cancelados = bloquear(b.id, origem.id, None, zeca.id, AGORA)

    assert {str(c[1]) for c in cancelados} == {str(origem.id), str(do_colega.id)}
    assert _status(origem) == "CANCELADO_BARBEIRO"
    assert _status(do_colega) == "CANCELADO_BARBEIRO"
    assert _status(passado) == "CONFIRMADO"
    assert _status(ja_cancelado) == "CANCELADO_CLIENTE"


def test_bloquear_grava_quem_e_quando(cenario):
    from tenant.models import Cliente

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    c = Cliente.objects.using("owner").get(id=maria.id)
    assert c.bloqueado_em is not None
    assert str(c.bloqueado_por_id) == str(zeca.id)


def test_bloquear_de_novo_nao_cancela_nada(cenario):
    """O barbeiro marcou ela pelo painel depois do bloqueio (decisao dele).
    Apertar bloquear de novo nao pode desfazer isso."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)
    pelo_painel = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))

    assert bloquear(b.id, a.id, None, zeca.id, AGORA) == []
    assert _status(pelo_painel) == "CONFIRMADO"


def test_barbeiro_nao_bloqueia_pelo_agendamento_do_colega(cenario):
    b = cenario["brutus"]
    eu, colega = _barbeiro(b.id, "Eu"), _barbeiro(b.id, "Colega")
    a = _agendamento(b.id, colega, _cliente(b.id), AGORA + timedelta(days=1))

    assert bloquear(b.id, a.id, eu.id, eu.id, AGORA) is None
    assert previa(b.id, a.id, eu.id, AGORA) is None
    assert esta_bloqueado(b.id, "11977778888", None) is False


def test_previa_conta_os_horarios_que_seriam_cancelados(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    _agendamento(b.id, zeca, maria, AGORA + timedelta(days=2))
    _agendamento(b.id, zeca, maria, AGORA - timedelta(days=2))

    assert previa(b.id, a.id, None, AGORA) == {
        "clienteId": str(maria.id), "nome": "Maria", "whatsapp": "11977778888",
        "horarios": 2, "bloqueado": False,
    }


# ------------------------------------------------------ listar / desbloquear


def test_listar_traz_os_bloqueados_com_quem_bloqueou(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    _cliente(b.id, whatsapp="11955554444", nome="Livre")
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    lista = listar(b.id)
    assert [(c["id"], c["nome"], c["whatsapp"], c["bloqueadoPor"]) for c in lista] == [
        (str(maria.id), "Maria", "11977778888", "Zeca"),
    ]
    assert lista[0]["bloqueadoEm"] is not None


def test_desbloquear_libera_numero_e_aparelho(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1), aparelho="cel")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert desbloquear(b.id, maria.id) is True
    assert esta_bloqueado(b.id, "11977778888", None) is False
    assert esta_bloqueado(b.id, "11966665555", "cel") is False
    assert listar(b.id) == []
    # Os horarios cancelados no bloqueio nao voltam.
    assert _status(a) == "CANCELADO_BARBEIRO"


def test_desbloquear_cliente_de_outra_barbearia_nao_acha(cenario):
    b, d = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert desbloquear(d.id, maria.id) is False
    assert esta_bloqueado(b.id, "11977778888", None) is True
