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
from app.services.whatsapp import Aceita
from tenant.datas import dia_de_hoje, local_para_utc
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    Cliente,
    ListaDoDiaEnviada,
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


def _rodar(aceita=Aceita("ID-07H", "jid-07h")):
    with patch.object(lista_do_dia, "enviar_a_equipe_aceita", return_value=aceita) as envia:
        enviados = lista_do_dia.enviar(AGORA)
    return enviados, {c.args[0]: c.args[1] for c in envia.call_args_list}


def test_a_lista_das_7_sai_pelo_central_e_fica_guardada(cenario):
    """Guardada para poder ser APAGADA quando a agenda de hoje mudar."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    _rodar()

    linha = ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id)
    assert (str(linha.dia), linha.mensagem_id, linha.remote_jid) == (
        dia_de_hoje(AGORA), "ID-07H", "jid-07h",
    )


@pytest.mark.parametrize("aceita", [None, Aceita(None, "jid"), Aceita("id", None)])
def test_lista_que_nao_saiu_ou_sem_id_nao_e_guardada(cenario, aceita):
    """Guardar sem id faria a proxima mudanca tentar apagar `None`."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    _rodar(aceita)
    assert not ListaDoDiaEnviada.objects.using("owner").filter(barbeiro_id=zeca.id).exists()


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


# ------------------------------------------------- a lista que se refaz

TARDE = local_para_utc("2026-09-16", 10 * 60)


def _guardada(barbearia, barbeiro, mensagem_id="ID-ANTIGA", jid="jid-antiga"):
    return ListaDoDiaEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, barbeiro_id=barbeiro.id,
        dia=dia_de_hoje(AGORA), mensagem_id=mensagem_id, remote_jid=jid,
    )


def _refazer(barbearia, barbeiro, novos=(), cancelados=(), aceita=Aceita("ID-NOVA", "jid-nova"),
             apagou=True, agora=TARDE):
    with patch.object(lista_do_dia, "apagar_para_todos", return_value=apagou) as apagar, \
            patch.object(lista_do_dia, "enviar_a_equipe_aceita", return_value=aceita) as envia:
        resultado = lista_do_dia.refazer(
            str(barbearia.id), str(barbeiro.id),
            [str(a.id) for a in novos], [str(a.id) for a in cancelados], agora,
        )
    return resultado, apagar, envia


def test_refazer_apaga_a_anterior_e_manda_a_nova_com_o_novo_marcado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Ja estava")
    novo = _agendamento(b, zeca, 15 * 60, cliente_nome="Acabou de marcar")
    _guardada(b, zeca)

    resultado, apagar, envia = _refazer(b, zeca, novos=[novo])

    assert resultado == "refeita"
    apagar.assert_called_once_with("jid-antiga", "ID-ANTIGA")
    destino, texto = envia.call_args.args
    assert destino == zeca.whatsapp
    assert texto.startswith("Zeca, sua agenda de hoje mudou:")
    assert "\nJa estava ·" in texto
    assert "🆕 Acabou de marcar ·" in texto
    linha = ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id)
    assert (linha.mensagem_id, linha.remote_jid) == ("ID-NOVA", "jid-nova")


def test_refazer_risca_o_cancelado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Fica")
    saiu = _agendamento(
        b, zeca, 11 * 60, cliente_nome="Desmarcou",
        status=StatusAgendamento.CANCELADO_CLIENTE,
    )

    _, _, envia = _refazer(b, zeca, cancelados=[saiu])
    texto = envia.call_args.args[1]
    assert "~Desmarcou · hoje 11:00 ·" in texto and texto.endswith("~ cancelou")
    assert "\nFica ·" in texto


def test_cancelado_de_antes_nao_aparece_na_lista_refeita(cenario):
    """O riscado vale so' na lista daquela mudanca."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)
    _agendamento(b, zeca, 11 * 60, cliente_nome="Saiu ontem",
                 status=StatusAgendamento.CANCELADO_CLIENTE)
    novo = _agendamento(b, zeca, 15 * 60)

    _, _, envia = _refazer(b, zeca, novos=[novo])
    assert "Saiu ontem" not in envia.call_args.args[1]


def test_refazer_sem_lista_anterior_so_manda(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    resultado, apagar, envia = _refazer(b, zeca, novos=[novo])
    assert resultado == "refeita"
    apagar.assert_not_called()
    envia.assert_called_once()


def test_refazer_manda_mesmo_se_apagar_falhar(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    resultado, _, envia = _refazer(b, zeca, novos=[novo], apagou=False)
    assert resultado == "refeita"
    envia.assert_called_once()


def test_refazer_sem_horario_restante_avisa(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    saiu = _agendamento(b, zeca, 11 * 60, status=StatusAgendamento.CANCELADO_BARBEIRO)

    _, _, envia = _refazer(b, zeca, cancelados=[saiu])
    assert envia.call_args.args[1].endswith("Não sobrou horário hoje.")


def test_duas_mudancas_seguidas_a_segunda_apaga_a_lista_da_primeira(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    primeiro = _agendamento(b, zeca, 14 * 60)
    segundo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca, "ID-07H", "jid-07h")

    _refazer(b, zeca, novos=[primeiro], aceita=Aceita("ID-1", "jid-1"))
    _, apagar, _ = _refazer(b, zeca, novos=[segundo], aceita=Aceita("ID-2", "jid-2"))

    apagar.assert_called_once_with("jid-1", "ID-1")
    assert ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id).mensagem_id == "ID-2"


def test_barbeiro_desativado_nao_recebe_lista_refeita(cenario):
    b = cenario["brutus"]
    saiu = _barbeiro(b, "Ja Foi", ativo=False)
    novo = _agendamento(b, saiu, 15 * 60)

    resultado, _, envia = _refazer(b, saiu, novos=[novo])
    assert resultado == "sem_barbeiro"
    envia.assert_not_called()


def test_envio_recusado_mantem_a_linha_anterior(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    resultado, _, _ = _refazer(b, zeca, novos=[novo], aceita=None)
    assert resultado == "nao_saiu"
    assert ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id).mensagem_id == "ID-ANTIGA"


def test_refazer_sem_url_nao_quebra(cenario, monkeypatch):
    """Desenvolvimento, sem Evolution: tudo devolve None/False e nada levanta."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    assert lista_do_dia.refazer(str(b.id), str(zeca.id), [str(novo.id)], [], TARDE) == "nao_saiu"


# ------------------------------------------------- quando enfileirar


def _avisar(barbearia, barbeiro, agora, novos=(), cancelados=()):
    return lista_do_dia.avisar_mudanca(
        barbearia.id, barbeiro.id, agora,
        novos=[(a.id, a.inicio) for a in novos],
        cancelados=[(a.id, a.inicio) for a in cancelados],
    )


def test_mudanca_de_hoje_depois_das_7_enfileira(cenario, refazer_enfileirado):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, TARDE, novos=[novo]) is True
    refazer_enfileirado.assert_called_once_with(str(b.id), str(zeca.id), [str(novo.id)], [])


def test_mudanca_de_hoje_as_6_59_nao_enfileira(cenario, refazer_enfileirado):
    """Antes das 07:00 a mudanca entra na lista das 07:00."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, local_para_utc("2026-09-16", 6 * 60 + 59), novos=[novo]) is False
    refazer_enfileirado.assert_not_called()


def test_mudanca_de_hoje_as_7_em_ponto_enfileira(cenario, refazer_enfileirado):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, AGORA, novos=[novo]) is True


def test_mudanca_de_amanha_nao_enfileira(cenario, refazer_enfileirado):
    from tenant.datas import somar_dias

    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    amanha = _agendamento(b, zeca, 15 * 60, dia=somar_dias(dia_de_hoje(AGORA), 1))

    assert _avisar(b, zeca, TARDE, novos=[amanha]) is False
    refazer_enfileirado.assert_not_called()


def test_so_os_de_hoje_vao_para_a_fila(cenario, refazer_enfileirado):
    """Um bloqueio pode derrubar hoje e amanha de uma vez."""
    from tenant.datas import somar_dias

    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    hoje = _agendamento(b, zeca, 15 * 60)
    amanha = _agendamento(b, zeca, 15 * 60, dia=somar_dias(dia_de_hoje(AGORA), 1))

    assert _avisar(b, zeca, TARDE, cancelados=[hoje, amanha]) is True
    refazer_enfileirado.assert_called_once_with(str(b.id), str(zeca.id), [], [str(hoje.id)])
