"""A lista das 07:00.

Duas regras foram decididas e sao o que estes casos prendem: **cada um recebe
so os proprios horarios, o dono inclusive** e **dia vazio nao manda nada.** As
duas existem pelo mesmo motivo — uma mensagem diaria que traz ruido vira uma
mensagem que a pessoa aprende a nao ler, e ai a util se perde junto.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.services import lista_do_dia
from tenant.datas import dia_de_hoje, local_para_utc
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    Cliente,
    Servico,
    StatusAgendamento,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

# 07:00 de Sao Paulo num dia FIXO — a hora em que a tarefa roda de verdade.
# Data fixa, e nao `now()`, porque um `now()` faria estes casos falharem so
# entre 21:00 e 00:00 (quando a data local e a UTC divergem), que e o pior
# tipo de teste: verde o dia todo e vermelho na hora de sair.
AGORA = local_para_utc("2026-09-16", 7 * 60)


def _barbeiro(barbearia, nome, papel="BARBEIRO", ativo=True):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=ativo,
    )


def _agendamento(barbearia, barbeiro, minutos_do_dia, cliente_nome="Ana", status=None, dia=None):
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=30, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=cliente_nome,
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    inicio = local_para_utc(dia or dia_de_hoje(AGORA), minutos_do_dia)
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico.nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status or StatusAgendamento.CONFIRMADO,
    )


def _rodar():
    with patch.object(lista_do_dia, "enviar_a_equipe_da") as envia:
        enviados = lista_do_dia.enviar(AGORA)
    return enviados, {c.args[1]: c.args[2] for c in envia.call_args_list}


def test_a_lista_sai_pela_equipe_da_propria_barbearia(cenario):
    """A barbearia vai junto: e' ela que decide se o aviso sai pelo numero
    dela (barbeiro que e' o proprio numero) ou pelo central."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    with patch.object(lista_do_dia, "enviar_a_equipe_da") as envia:
        lista_do_dia.enviar(AGORA)

    assert [(str(c.args[0]), c.args[1]) for c in envia.call_args_list] == [(str(b.id), zeca.whatsapp)]


def test_cada_barbeiro_recebe_so_os_proprios_horarios(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    tonho = _barbeiro(b, "Tonho Lima")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Cliente do Zeca")
    _agendamento(b, tonho, 10 * 60, cliente_nome="Cliente do Tonho")

    enviados, mensagens = _rodar()

    assert enviados == 2
    assert "Cliente do Zeca" in mensagens[zeca.whatsapp]
    assert "Cliente do Tonho" not in mensagens[zeca.whatsapp]
    assert "Cliente do Tonho" in mensagens[tonho.whatsapp]


def test_o_dono_tambem_recebe_so_os_dele(cenario):
    """O dono ja ve a agenda inteira no painel. Receber a de todo mundo todo
    dia as sete da manha e ruido, nao servico."""
    b = cenario["brutus"]
    dono = _barbeiro(b, "Dona Chefe", papel="DONO")
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, dono, 9 * 60, cliente_nome="Cliente do Dono")
    _agendamento(b, zeca, 10 * 60, cliente_nome="Cliente do Zeca")

    _, mensagens = _rodar()

    assert "Cliente do Dono" in mensagens[dono.whatsapp]
    assert "Cliente do Zeca" not in mensagens[dono.whatsapp]


def test_quem_nao_tem_horario_nao_recebe_nada(cenario):
    """"Voce nao tem horario hoje" e a mensagem que ensina a ignorar as
    proximas."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    vazio = _barbeiro(b, "Sem Horario")
    _agendamento(b, zeca, 9 * 60)

    enviados, mensagens = _rodar()

    assert enviados == 1
    assert vazio.whatsapp not in mensagens


def test_cancelado_nao_entra_na_lista(cenario):
    """So CONFIRMADO ocupa a agenda — uma lista que trouxesse cancelados faria
    o barbeiro esperar por quem desmarcou."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Quem vem")
    _agendamento(
        b, zeca, 11 * 60, cliente_nome="Quem desmarcou",
        status=StatusAgendamento.CANCELADO_CLIENTE,
    )

    _, mensagens = _rodar()
    assert "Quem vem" in mensagens[zeca.whatsapp]
    assert "Quem desmarcou" not in mensagens[zeca.whatsapp]


def test_horario_de_amanha_nao_entra(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="De hoje")
    from tenant.datas import somar_dias

    _agendamento(
        b, zeca, 9 * 60, cliente_nome="De amanha", dia=somar_dias(dia_de_hoje(AGORA), 1),
    )

    _, mensagens = _rodar()
    assert "De hoje" in mensagens[zeca.whatsapp]
    assert "De amanha" not in mensagens[zeca.whatsapp]


def test_horario_da_noite_de_ontem_nao_entra(cenario):
    """O recorte e no fuso de Sao Paulo. Feito em UTC, ele pegaria das 21:00 de
    ontem as 21:00 de hoje — e a lista sairia com a noite anterior dentro."""
    from tenant.datas import somar_dias

    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="De hoje")
    _agendamento(
        b, zeca, 22 * 60, cliente_nome="De ontem a noite",
        dia=somar_dias(dia_de_hoje(AGORA), -1),
    )

    _, mensagens = _rodar()
    assert "De ontem a noite" not in mensagens[zeca.whatsapp]


def test_barbeiro_desativado_nao_recebe(cenario):
    b = cenario["brutus"]
    saiu = _barbeiro(b, "Ja Foi", ativo=False)
    _agendamento(b, saiu, 9 * 60)

    enviados, mensagens = _rodar()
    assert enviados == 0
    assert saiu.whatsapp not in mensagens


def test_sai_nos_dois_planos(cenario):
    """E no plano SEM ZAP que ela mais importa: la o cliente nao recebe nada, e
    sem isto o barbeiro tambem nao saberia da agenda sem abrir o painel."""
    b = cenario["brutus"]
    assert b.plano == "SEM_ZAP"
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    enviados, _ = _rodar()
    assert enviados == 1


def test_barbearia_desativada_nao_recebe(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)
    Barbearia.objects.using("owner").filter(id=b.id).update(ativo=False)

    enviados, _ = _rodar()
    assert enviados == 0


def test_a_lista_nao_atravessa_barbearias(cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b, "Zeca Silva")
    de_fora = _barbeiro(outra, "De Outra")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Cliente daqui")
    _agendamento(outra, de_fora, 9 * 60, cliente_nome="Cliente de la")

    _, mensagens = _rodar()
    assert "Cliente de la" not in mensagens[zeca.whatsapp]
    assert "Cliente daqui" not in mensagens[de_fora.whatsapp]


def test_a_mensagem_cumprimenta_e_lista_em_ordem(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 14 * 60, cliente_nome="Da tarde")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Da manha")

    _, mensagens = _rodar()
    texto = mensagens[zeca.whatsapp]

    assert texto.startswith("Bom dia, Zeca!")
    assert texto.index("Da manha") < texto.index("Da tarde")
