from tenant.datas import (
    formatar_dia_com_semana,
    formatar_dia_relativo,
    formatar_hora,
    formatar_hora_falada,
)

# Todo texto que sai pelo WhatsApp mora aqui — espalhar template pelas rotas e
# como duas mensagens do mesmo evento acabam divergindo.
#
# Nasceu como porte fiel de marcai-front/src/lib/mensagens.ts. Aquele arquivo
# ainda existe e ninguem mais o importa: quem manda WhatsApp e o Django desde a
# travessia. Ele NAO acompanha mais este; nao o use como referencia.
#
# ---- Sobre o tamanho destes textos -------------------------------------
#
# Sao curtos de proposito, e isso foi pedido: no celular, uma mensagem de tres
# paragrafos chega cortada com um "Ler mais" em cima justamente da parte que
# importa (o dia e a hora). Uma linha cabe inteira na previa da notificacao —
# o cliente entende sem abrir.
#
# A data vai em "quinta 10/09 as 9:00" — o dia da semana por extenso, a data em
# numero, e a hora sem zero a esquerda (pedido do dono, 06/09).
#
# Isto REVERTE a decisao de 02/09, que tinha tirado o dia da semana com o
# argumento de que ele obriga a traduzir para uma data. O argumento nao estava
# errado; estava incompleto. Os dois respondem perguntas diferentes: o numero
# diz quando e' (da' para conferir no calendario), o nome do dia diz se DA' para
# ir. Quem usou pediu os dois de volta, e usar ganha do argumento.
#
# As mensagens do BARBEIRO (mais abaixo) continuam com outra regra —
# "hoje"/"amanha" — que e' melhor ainda para quem le no meio do expediente.
#
# O que NAO se corta e o link de cancelar: sem ele, todo cliente que desistiu
# vira uma ligacao pro barbeiro no meio de um corte, e um horario que fica
# ocupado a toa porque ninguem avisou.


def _capitalizar(texto: str) -> str:
    """Primeira letra maiuscula, o RESTO intacto.

    `.capitalize()` do Python nao serve: ele rebaixa o resto, e "Corte de
    Cabelo" viraria "Corte de cabelo" — o nome do servico e' do barbeiro, nao
    nosso. Existe porque o nome do servico agora ABRE frase; antes vinha no
    meio de uma, em minuscula.
    """
    return texto[:1].upper() + texto[1:]


def msg_confirmacao(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str, link: str,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    # O endereco SAIU daqui (pedido do dono, 02/09): quem marca ja esta na
    # vitrine da barbearia, que o mostra, e repeti-lo era o que empurrava a
    # mensagem para tres paragrafos. `endereco` continua no parametro de
    # proposito — quem chama nao muda, e o lembrete (que chega quando a pessoa
    # esta de fato saindo de casa) ainda e o lugar certo para ele.
    return (
        f"Fechou, {primeiro_nome}! {_capitalizar(servico_nome)} "
        f"{formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome}.\n\nCancelar: {link}"
    )


def msg_cancelamento_pela_barbearia(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    # O pedido de desculpa FICA, encurtado. Foi a barbearia que desmarcou: uma
    # mensagem seca aqui e' a diferenca entre um cliente que remarca e um que
    # nao volta. O convite a remarcar tambem fica, pela mesma razao.
    return (
        f"Oi, {primeiro_nome}. Cancelamos seu {servico_nome.lower()} de "
        f"{formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}. "
        f"Desculpa! Chama a gente pra remarcar."
    )


def msg_cancelamento(*, barbeiro_nome: str, inicio) -> str:
    """O cliente que cancelou o PRÓPRIO horário — por isso, ao contrário de
    `msg_cancelamento_pela_barbearia`, nao ha "Oi, fulano" nem pedido de
    desculpa: mandar isso pra quem acabou de cancelar seria estranho, nao
    gentil. Espelha `msgCancelamento` (mensagens.ts), que tambem ignora
    `clienteNome`/`servicoNome`/`endereco` apesar de aceita-los no tipo.
    """
    return (
        f"Horário de {formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome} cancelado. Até a próxima!"
    )


def msg_lembrete(*, servico_nome: str, barbeiro_nome: str, inicio, endereco: str) -> str:
    # O endereco FICA so' aqui. Esta e' a mensagem que chega quando a pessoa
    # esta saindo de casa — e' o unico momento em que ele e' util, e por isso
    # ele saiu da confirmacao e nao daqui.
    return (
        f"Lembrete: {servico_nome.lower()} hoje às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome}. {endereco}"
    )


def msg_convite(*, nome: str, barbearia_nome: str, link: str) -> str:
    primeiro_nome = nome.split(" ")[0]
    return (
        f"Oi, {primeiro_nome}! Você entrou na equipe da {barbearia_nome}. "
        f"Cria sua senha por aqui pra ver sua agenda:\n\n{link}\n\n"
        f"O link vale por 48 horas."
    )


# --- Avisos para o BARBEIRO ---------------------------------------------
#
# Ate aqui o WhatsApp so falava com o CLIENTE, e o barbeiro so descobria uma
# marcacao nova abrindo o painel. Estas duas sao deliberadamente CURTAS: ele
# le de pe, entre um corte e outro.
#
# Sem endereco, ao contrario das mensagens do cliente — ele trabalha la. E com
# o nome INTEIRO, ao contrario delas tambem: "Fechou, Jose!" soa pessoal para
# quem marcou, mas o barbeiro precisa separar dois Joses da agenda do dia.


def _linha_do_horario(*, cliente_nome: str, servico_nome: str, inicio, agora) -> str:
    return (
        f"{cliente_nome} · {formatar_dia_relativo(inicio, agora)} "
        f"{formatar_hora(inicio)} · {servico_nome}"
    )


def msg_barbeiro_novo(*, cliente_nome: str, servico_nome: str, inicio, agora) -> str:
    return "Novo horário\n" + _linha_do_horario(
        cliente_nome=cliente_nome, servico_nome=servico_nome, inicio=inicio, agora=agora,
    )


def msg_barbeiro_cancelado(*, cliente_nome: str, servico_nome: str, inicio, agora) -> str:
    return "Cancelou\n" + _linha_do_horario(
        cliente_nome=cliente_nome, servico_nome=servico_nome, inicio=inicio, agora=agora,
    )


def msg_lista_do_dia(*, barbeiro_nome: str, agendamentos: list[dict], agora) -> str:
    """A agenda do dia, uma linha por horario, na MESMA forma do aviso de
    horario novo (`_linha_do_horario`).

    Reaproveitar aquela linha nao e economia de codigo: o barbeiro le as duas
    mensagens no mesmo lugar, e duas formas diferentes de escrever a mesma
    informacao obrigariam a reaprender a leitura toda manha.

    So o primeiro nome no cabecalho ("Bom dia, Zeca"), e o nome INTEIRO do
    cliente em cada linha — e quem separa dois Joses da agenda do dia.
    """
    cabecalho = f"Bom dia, {barbeiro_nome.split()[0]}! Hoje você tem:"
    linhas = [
        _linha_do_horario(
            cliente_nome=a["cliente_nome"], servico_nome=a["servico_nome"],
            inicio=a["inicio"], agora=agora,
        )
        for a in agendamentos
    ]
    return cabecalho + "\n" + "\n".join(linhas)


# ---- O bot de agendamento -------------------------------------------------
#
# Menu NUMERADO, e o numero sozinho e' a unica coisa que o bot entende (spec,
# secao 2). Toda pergunta termina numa lista "1 - ...", e o "0" e' sempre a
# saida para gente de verdade.

FALAR_COM_A_BARBEARIA = "0 - Falar com a barbearia"

_CABECALHO_DO_PASSO = {
    "SERVICO": "Qual serviço?",
    "BARBEIRO": "Com quem?",
    "DIA": "Qual dia?",
    "QUAL_AGENDAMENTO": "Qual horário você quer cancelar?",
}

_OPCOES_DO_LEMBRETE = "1 - Confirmar\n2 - Não vou conseguir ir"


def _numerada(opcoes: list[dict]) -> str:
    return "\n".join(f"{i} - {o['rotulo']}" for i, o in enumerate(opcoes, start=1))


def rotulo_do_agendamento(*, barbeiro_nome: str, inicio) -> str:
    return (
        f"{barbeiro_nome}, {formatar_dia_com_semana(inicio)} "
        f"às {formatar_hora_falada(inicio)}"
    )


def rotulo_da_hora(*, inicio, barbeiro_nome: str | None) -> str:
    """O barbeiro so' aparece quando o cliente escolheu "tanto faz": ai' e' a
    unica forma de ele saber com quem vai cortar."""
    hora = formatar_hora_falada(inicio)
    return f"{hora} com {barbeiro_nome}" if barbeiro_nome else hora


def msg_bot_pergunta(*, passo: str, opcoes: list[dict], contexto: dict) -> str:
    lista = _numerada(opcoes)
    if passo == "MENU":
        partes = [f"Oi! Aqui é o atendimento da {contexto['barbearia_nome']}."]
        marcados = contexto.get("agendamentos") or []
        if len(marcados) == 1:
            partes.append(f"Você tem: {marcados[0]}.")
        elif marcados:
            partes.append("Você tem:\n" + "\n".join(marcados))
        partes.append(f"{lista}\n{FALAR_COM_A_BARBEARIA}")
        return "\n\n".join(partes)
    if passo == "NOME":
        return "Pra marcar, me diz seu nome:"
    if passo == "HORA":
        return f"Horários de {contexto['dia_rotulo']}:\n\n{lista}"
    if passo == "CONFIRMA":
        inicio = contexto["inicio"]
        return (
            f"Confere:\n{_capitalizar(contexto['servico_nome'])} com "
            f"{contexto['barbeiro_nome']}, {formatar_dia_com_semana(inicio)} "
            f"às {formatar_hora_falada(inicio)}.\n\n{lista}"
        )
    if passo == "CONFIRMA_CANCEL":
        return f"Cancelar {contexto['agendamento_rotulo']}?\n\n{lista}"
    return f"{_CABECALHO_DO_PASSO[passo]}\n\n{lista}"


def msg_bot_nao_entendi(*, pergunta: str, mostrar_zero: bool) -> str:
    texto = f"Não entendi. Responde só com o número.\n\n{pergunta}"
    if mostrar_zero and FALAR_COM_A_BARBEARIA not in pergunta:
        texto += f"\n{FALAR_COM_A_BARBEARIA}"
    return texto


def msg_bot_nao_entendi_nome(*, mostrar_zero: bool) -> str:
    """NOME e' o unico passo de texto livre (ver `conversa.decidir`): pedir
    'responde so com o numero' ali contradiz a pergunta seguinte, que pede
    exatamente o contrario."""
    texto = "Não entendi. Me diz seu nome (só letras, pelo menos 2)."
    if mostrar_zero:
        texto += f"\n{FALAR_COM_A_BARBEARIA}"
    return texto


def msg_bot_chamou_humano() -> str:
    return "Beleza, já chamei alguém da barbearia. Te respondem por aqui."


def msg_bot_pediu_humano(*, cliente: str) -> str:
    """Para o DONO, pelo numero central."""
    return f"Cliente pediu atendimento no WhatsApp da barbearia\n{cliente}"


def msg_bot_sem_opcoes(*, passo: str) -> str:
    if passo in ("QUAL_AGENDAMENTO", "CONFIRMA_CANCEL"):
        return (
            "Não achei horário marcado neste número. "
            "Responde 0 que alguém da barbearia te atende."
        )
    return (
        "Não achei horário livre nos próximos dias. "
        "Responde 0 que alguém da barbearia te atende."
    )


def msg_bot_fora_do_prazo() -> str:
    return (
        "Faltando menos de 1h não dá pra cancelar por aqui. "
        "Responde 0 que alguém da barbearia te atende."
    )


def msg_bot_nao_achei_agendamento() -> str:
    return "Não achei esse horário marcado neste número."


def msg_bot_lembrete_confirmado() -> str:
    return "Combinado, te esperamos!"


def msg_bot_desistencia_avisada() -> str:
    return "Tudo bem, avisei a barbearia. Obrigado por avisar!"


def msg_barbeiro_desistiu(*, cliente_nome: str, servico_nome: str, inicio, agora) -> str:
    return "Avisou que não vem\n" + _linha_do_horario(
        cliente_nome=cliente_nome, servico_nome=servico_nome, inicio=inicio, agora=agora,
    )


def msg_lembrete_com_opcoes(*, lembrete: str) -> str:
    """O lembrete de sempre, com as duas respostas que o bot entende. "Nao vou
    conseguir ir" e nao "cancelar": o lembrete sai 60 minutos antes, e o
    cliente so' cancela com mais de 60 — um "cancelar" aqui daria sempre fora
    do prazo."""
    return f"{lembrete}\n\n{_OPCOES_DO_LEMBRETE}"


def msg_bot_pergunta_do_lembrete() -> str:
    return f"Responde 1 pra confirmar ou 2 se não for conseguir ir.\n\n{_OPCOES_DO_LEMBRETE}"
