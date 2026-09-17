"""A maquina do bot, sem banco e sem rede.

Cada caso daqui e' um jeito de o bot errar caro — marcar o horario errado,
repetir o mesmo menu para sempre, agir sobre uma conversa de ontem.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import conversa as c
from tenant.models import EstadoConversa

AGORA = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
LISTA_DE_TRES = [{"id": f"s{i}", "rotulo": f"Serviço {i}"} for i in (1, 2, 3)]


def _estado(passo=c.SERVICO, opcoes=None, rascunho=None, tentativas=0, ha_min=1):
    return c.Estado(
        passo=passo,
        opcoes=LISTA_DE_TRES if opcoes is None else opcoes,
        rascunho=rascunho or {},
        tentativas=tentativas,
        atualizado_em=AGORA - timedelta(minutes=ha_min),
    )


def test_os_passos_sao_os_mesmos_do_banco():
    for passo in (c.MENU, c.SERVICO, c.BARBEIRO, c.DIA, c.HORA, c.NOME, c.CONFIRMA,
                  c.QUAL_AGENDAMENTO, c.CONFIRMA_CANCEL, c.AGUARDANDO_LEMBRETE):
        assert passo in EstadoConversa.values


@pytest.mark.parametrize("texto, numero", [
    ("1", 1), (" 2 ", 2), ("2.", 2), ("3)", 3), ("10", 10), ("0", 0),
])
def test_numero_sozinho_e_escolha(texto, numero):
    assert c.numero_escolhido(texto) == numero


@pytest.mark.parametrize("texto", ["quero o 1", "às 14", "1 e 2", "", "um", None, "123"])
def test_numero_no_meio_de_frase_nao_e_escolha(texto):
    """"as 14" virando a opcao 14 marcaria um horario que a pessoa so'
    estava mencionando."""
    assert c.numero_escolhido(texto) is None


def test_conversa_que_nunca_existiu_vai_ao_menu():
    estado = c.Estado(c.MENU, [], {}, 0, None)
    assert c.decidir(estado, "oi", AGORA) == c.Ir(c.MENU, {})


def test_conversa_velha_recomeca_mesmo_com_numero_valido():
    """Um "1" digitado amanha nao confirma o que foi escolhido hoje."""
    estado = _estado(ha_min=21)
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.MENU, {})


def test_resposta_ao_lembrete_vale_mais_que_vinte_minutos():
    opcoes = [{"id": "confirmar:abc", "rotulo": "Confirmar"}]
    assert c.decidir(_estado(c.AGUARDANDO_LEMBRETE, opcoes, ha_min=45), "1", AGORA) == (
        c.ConfirmarLembrete("abc")
    )
    assert c.decidir(_estado(c.AGUARDANDO_LEMBRETE, opcoes, ha_min=61), "1", AGORA) == (
        c.Ir(c.MENU, {})
    )


@pytest.mark.parametrize("passo", [c.MENU, c.SERVICO, c.HORA, c.CONFIRMA, c.NOME])
def test_zero_chama_gente_em_qualquer_passo(passo):
    assert c.decidir(_estado(passo), "0", AGORA) == c.ChamarHumano()


def test_zero_chama_gente_mesmo_com_conversa_expirada():
    """"0" nao depende da conversa estar fresca: quem digita "0" numa
    conversa de ontem ainda quer falar com alguem, nao recomecar o menu."""
    estado = _estado(ha_min=21)
    assert c.decidir(estado, "0", AGORA) == c.ChamarHumano()


def test_zero_funciona_depois_de_um_beco_sem_opcoes():
    """Depois de "nao achei horario, responde 0", a conversa fica no MENU sem
    opcoes. O 0 tem que valer ali — foi o que a mensagem mandou fazer."""
    assert c.decidir(_estado(c.MENU, opcoes=[]), "0", AGORA) == c.ChamarHumano()


def test_sem_opcoes_guardadas_mostra_o_menu():
    assert c.decidir(_estado(c.MENU, opcoes=[]), "1", AGORA) == c.Ir(c.MENU, {})


@pytest.mark.parametrize("texto", ["9", "4", "oi", "pode ser"])
def test_fora_da_lista_repete_e_conta(texto):
    assert c.decidir(_estado(tentativas=1), texto, AGORA) == c.Repetir(2)


def test_menu_marcar_leva_o_nome_ja_conhecido():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "Marcar horário"}],
                     {"cliente_nome": "Maria"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.SERVICO, {"cliente_nome": "Maria"})


def test_menu_com_um_horario_vai_direto_confirmar_o_cancelamento():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "x"},
                              {"id": "cancelar:abc123", "rotulo": "y"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.CONFIRMA_CANCEL, {"codigo": "abc123"})


def test_menu_com_varios_horarios_pergunta_qual():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "x"},
                              {"id": "cancelar", "rotulo": "y"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.QUAL_AGENDAMENTO, {})


def test_servico_escolhido_segue_para_o_barbeiro_sem_perder_o_nome():
    estado = _estado(c.SERVICO, rascunho={"cliente_nome": "Maria"})
    assert c.decidir(estado, "2", AGORA) == c.Ir(
        c.BARBEIRO, {"cliente_nome": "Maria", "servico_id": "s2"}
    )


def test_barbeiro_escolhido_segue_para_o_dia():
    estado = _estado(c.BARBEIRO, [{"id": "b1", "rotulo": "Pedro"}], {"servico_id": "s1"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(
        c.DIA, {"servico_id": "s1", "barbeiro_id": "b1", "de": None}
    )


def test_outros_dias_avanca_a_janela():
    estado = _estado(c.DIA, [{"id": "2026-09-16", "rotulo": "hoje"},
                             {"id": "mais:2026-09-22", "rotulo": "Outros dias"}],
                     {"de": None})
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.DIA, {"de": "2026-09-22"})


def test_dia_escolhido_segue_para_a_hora():
    estado = _estado(c.DIA, [{"id": "2026-09-17", "rotulo": "amanhã"}], {"de": None})
    assert c.decidir(estado, "1", AGORA) == c.Ir(
        c.HORA, {"de": None, "dia": "2026-09-17", "depois": None}
    )


HORARIOS = [
    {"id": "2026-09-17T12:00:00.000Z|b1", "rotulo": "9:00"},
    {"id": "depois:2026-09-17T12:00:00.000Z", "rotulo": "Mais tarde"},
    {"id": "outro_dia", "rotulo": "Outro dia"},
]


def test_hora_de_quem_ja_tem_nome_vai_confirmar():
    estado = _estado(c.HORA, HORARIOS, {"cliente_nome": "Maria", "barbeiro_id": "qualquer"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.CONFIRMA, {
        "cliente_nome": "Maria", "barbeiro_id": "qualquer",
        "inicio": "2026-09-17T12:00:00.000Z", "barbeiro_escolhido": "b1",
    })


def test_hora_de_quem_nao_tem_nome_pergunta_o_nome():
    estado = _estado(c.HORA, HORARIOS, {"cliente_nome": None})
    assert c.decidir(estado, "1", AGORA).passo == c.NOME


def test_mais_tarde_continua_no_mesmo_dia():
    estado = _estado(c.HORA, HORARIOS, {"dia": "2026-09-17"})
    assert c.decidir(estado, "2", AGORA) == c.Ir(
        c.HORA, {"dia": "2026-09-17", "depois": "2026-09-17T12:00:00.000Z"}
    )


def test_outro_dia_volta_para_os_dias_do_comeco():
    estado = _estado(c.HORA, HORARIOS, {"dia": "2026-09-17", "depois": "x", "de": "y"})
    assert c.decidir(estado, "3", AGORA) == c.Ir(
        c.DIA, {"dia": "2026-09-17", "depois": None, "de": None}
    )


@pytest.mark.parametrize("escolha", ["sem-pipe-aqui", "depois:"])
def test_hora_malformada_volta_ao_menu_em_vez_de_estourar(escolha):
    """Um id de HORA sem "|" (ou um "depois:" sem timestamp atras) nao e'
    algo que a casca deveria mandar, mas a maquina nao pode estourar por
    causa disso — volta ao menu, como qualquer escolha nao reconhecida."""
    opcoes = [{"id": escolha, "rotulo": "x"}]
    estado = _estado(c.HORA, opcoes, {"dia": "2026-09-17"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.MENU, {})


def test_nome_valido_segue_para_confirmar_sem_espacos_sobrando():
    estado = _estado(c.NOME, opcoes=[], rascunho={"servico_id": "s1"})
    assert c.decidir(estado, "  João   da Silva ", AGORA) == c.Ir(
        c.CONFIRMA, {"servico_id": "s1", "cliente_nome": "João da Silva"}
    )


@pytest.mark.parametrize("texto", ["1", "J", ""])
def test_nome_que_nao_e_nome_repete(texto):
    assert c.decidir(_estado(c.NOME, opcoes=[]), texto, AGORA) == c.Repetir(1)


def test_confirmar_marca_com_o_rascunho_inteiro():
    rascunho = {"servico_id": "s1", "inicio": "x", "barbeiro_escolhido": "b1"}
    estado = _estado(c.CONFIRMA, [{"id": "confirmar", "rotulo": "Confirmar"},
                                  {"id": "recomecar", "rotulo": "Começar de novo"}], rascunho)
    assert c.decidir(estado, "1", AGORA) == c.Marcar(rascunho)
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.MENU, {})


def test_qual_agendamento_leva_o_codigo_para_confirmar():
    estado = _estado(c.QUAL_AGENDAMENTO, [{"id": "cod1", "rotulo": "a"},
                                          {"id": "cod2", "rotulo": "b"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.CONFIRMA_CANCEL, {"codigo": "cod2"})


def test_confirmar_cancelamento():
    estado = _estado(c.CONFIRMA_CANCEL, [{"id": "sim", "rotulo": "Sim"},
                                         {"id": "nao", "rotulo": "Não"}], {"codigo": "cod1"})
    assert c.decidir(estado, "1", AGORA) == c.Cancelar("cod1")
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.MENU, {})


def test_confirmar_cancelamento_sem_codigo_no_rascunho_volta_ao_menu():
    """Nao e' pra acontecer — QUAL_AGENDAMENTO e' quem grava o codigo — mas
    se o rascunho chegar sem ele, a maquina nao pode estourar KeyError."""
    estado = _estado(c.CONFIRMA_CANCEL, [{"id": "sim", "rotulo": "Sim"}], {})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.MENU, {})


def test_lembrete_confirma_ou_avisa_que_nao_vai():
    opcoes = [{"id": "confirmar:cod1", "rotulo": "Confirmar"},
              {"id": "nao_vou:cod1", "rotulo": "Não vou conseguir ir"}]
    estado = _estado(c.AGUARDANDO_LEMBRETE, opcoes)
    assert c.decidir(estado, "1", AGORA) == c.ConfirmarLembrete("cod1")
    assert c.decidir(estado, "2", AGORA) == c.NaoVou("cod1")


def test_servico_unico_e_pulado():
    assert c.seguir_sozinho(c.SERVICO, {"cliente_nome": None}, [{"id": "s1", "rotulo": "Corte"}]) == (
        c.Ir(c.BARBEIRO, {"cliente_nome": None, "servico_id": "s1"})
    )


def test_barbeiro_unico_e_pulado():
    assert c.seguir_sozinho(c.BARBEIRO, {}, [{"id": "b1", "rotulo": "Pedro"}]).passo == c.DIA


@pytest.mark.parametrize("passo", [c.DIA, c.HORA, c.CONFIRMA, c.MENU])
def test_os_outros_passos_nunca_pulam(passo):
    """Um dia so' com vaga ainda e' uma escolha que a pessoa precisa ver."""
    assert c.seguir_sozinho(passo, {}, [{"id": "x", "rotulo": "x"}]) is None


def test_duas_opcoes_nao_pulam():
    assert c.seguir_sozinho(c.SERVICO, {}, LISTA_DE_TRES[:2]) is None
