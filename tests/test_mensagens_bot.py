from datetime import datetime, timedelta, timezone

from app.services.mensagens import (
    FALAR_COM_A_BARBEARIA,
    msg_barbeiro_desistiu,
    msg_bot_nao_entendi,
    msg_bot_pergunta,
    msg_bot_pergunta_do_lembrete,
    msg_bot_sem_opcoes,
    msg_lembrete_com_opcoes,
    rotulo_da_hora,
    rotulo_do_agendamento,
)

# 12:00 UTC = 9:00 em Sao Paulo, numa quinta.
QUINTA_9H = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
MARCAR = [{"id": "marcar", "rotulo": "Marcar horário"}]


def test_rotulo_do_agendamento_diz_quem_e_quando():
    assert rotulo_do_agendamento(barbeiro_nome="Pedro", inicio=QUINTA_9H) == (
        "Pedro, quinta 17/09 às 9:00"
    )


def test_rotulo_da_hora_so_diz_o_barbeiro_quando_foi_tanto_faz():
    assert rotulo_da_hora(inicio=QUINTA_9H, barbeiro_nome=None) == "9:00"
    assert rotulo_da_hora(inicio=QUINTA_9H, barbeiro_nome="Pedro") == "9:00 com Pedro"


def test_menu_de_quem_nao_tem_horario():
    texto = msg_bot_pergunta(
        passo="MENU", opcoes=MARCAR,
        contexto={"barbearia_nome": "Brutus", "agendamentos": []},
    )
    assert texto == (
        "Oi! Aqui é o atendimento da Brutus.\n\n"
        "1 - Marcar horário\n0 - Falar com a barbearia"
    )


def test_menu_de_quem_tem_um_horario_mostra_o_horario():
    texto = msg_bot_pergunta(
        passo="MENU",
        opcoes=[{"id": "marcar", "rotulo": "Marcar outro horário"},
                {"id": "cancelar:x", "rotulo": "Cancelar esse"}],
        contexto={"barbearia_nome": "Brutus",
                  "agendamentos": ["Pedro, quinta 17/09 às 9:00"]},
    )
    assert "Você tem: Pedro, quinta 17/09 às 9:00." in texto
    assert "2 - Cancelar esse" in texto


def test_hora_diz_de_que_dia_sao_os_horarios():
    texto = msg_bot_pergunta(
        passo="HORA", opcoes=[{"id": "x", "rotulo": "9:00"}],
        contexto={"dia_rotulo": "amanhã · qui 17 set"},
    )
    assert texto == "Horários de amanhã · qui 17 set:\n\n1 - 9:00"


def test_confirma_repete_o_que_vai_ser_marcado():
    texto = msg_bot_pergunta(
        passo="CONFIRMA",
        opcoes=[{"id": "confirmar", "rotulo": "Confirmar"},
                {"id": "recomecar", "rotulo": "Começar de novo"}],
        contexto={"servico_nome": "corte", "barbeiro_nome": "Pedro", "inicio": QUINTA_9H},
    )
    assert texto.startswith("Confere:\nCorte com Pedro, quinta 17/09 às 9:00.")
    assert texto.endswith("1 - Confirmar\n2 - Começar de novo")


def test_nome_e_pergunta_aberta():
    assert msg_bot_pergunta(passo="NOME", opcoes=[], contexto={}) == (
        "Pra marcar, me diz seu nome:"
    )


def test_nao_entendi_repete_a_pergunta_e_so_oferece_o_zero_quando_pedido():
    pergunta = "Qual dia?\n\n1 - hoje"
    sem = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=False)
    com = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=True)
    assert sem == "Não entendi. Responde só com o número.\n\nQual dia?\n\n1 - hoje"
    assert FALAR_COM_A_BARBEARIA not in sem
    assert com.endswith(f"1 - hoje\n{FALAR_COM_A_BARBEARIA}")


def test_nao_entendi_no_menu_nao_duplica_o_zero():
    pergunta = f"Oi!\n\n1 - Marcar horário\n{FALAR_COM_A_BARBEARIA}"
    texto = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=True)
    assert texto.count(FALAR_COM_A_BARBEARIA) == 1


def test_sem_opcoes_separa_falta_de_vaga_de_falta_de_horario_marcado():
    assert "horário livre" in msg_bot_sem_opcoes(passo="DIA")
    assert "horário marcado" in msg_bot_sem_opcoes(passo="QUAL_AGENDAMENTO")


def test_lembrete_ganha_as_duas_opcoes_no_fim():
    texto = msg_lembrete_com_opcoes(lembrete="Lembrete: corte hoje às 9:00, com Pedro.")
    assert texto == (
        "Lembrete: corte hoje às 9:00, com Pedro.\n\n"
        "1 - Confirmar\n2 - Não vou conseguir ir"
    )
    assert msg_bot_pergunta_do_lembrete().endswith("1 - Confirmar\n2 - Não vou conseguir ir")


def test_barbeiro_sabe_quem_desistiu_na_mesma_forma_das_outras_mensagens():
    texto = msg_barbeiro_desistiu(
        cliente_nome="Maria Souza", servico_nome="Corte",
        inicio=QUINTA_9H, agora=QUINTA_9H - timedelta(minutes=50),
    )
    assert texto == "Avisou que não vem\nMaria Souza · hoje 09:00 · Corte"
