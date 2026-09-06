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
