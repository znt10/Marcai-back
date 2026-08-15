from tenant.datas import formatar_dia_longo, formatar_hora

# Todo texto que sai pelo WhatsApp mora aqui. Porte fiel de
# marcai-front/src/lib/mensagens.ts — espalhar template pelas rotas e como
# duas mensagens do mesmo evento acabam divergindo.


def msg_confirmacao(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str, link: str,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    return (
        f"Fechou, {primeiro_nome}! Seu {servico_nome.lower()} "
        f"está marcado para {formatar_dia_longo(inicio)} às {formatar_hora(inicio)} "
        f"com {barbeiro_nome}.\n\n{endereco}\n\n"
        f"Precisa cancelar? {link}"
    )


def msg_cancelamento_pela_barbearia(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    return (
        f"Oi, {primeiro_nome}. Precisamos cancelar seu "
        f"{servico_nome.lower()} de {formatar_dia_longo(inicio)} às "
        f"{formatar_hora(inicio)} com {barbeiro_nome}. Desculpa pelo transtorno — "
        f"chama a gente que remarcamos."
    )


def msg_cancelamento(*, barbeiro_nome: str, inicio) -> str:
    """O cliente que cancelou o PRÓPRIO horário — por isso, ao contrário de
    `msg_cancelamento_pela_barbearia`, nao ha "Oi, fulano" nem pedido de
    desculpa: mandar isso pra quem acabou de cancelar seria estranho, nao
    gentil. Espelha `msgCancelamento` (mensagens.ts), que tambem ignora
    `clienteNome`/`servicoNome`/`endereco` apesar de aceita-los no tipo.
    """
    return (
        f"Seu horário de {formatar_dia_longo(inicio)} às {formatar_hora(inicio)} "
        f"com {barbeiro_nome} foi cancelado. Até a próxima!"
    )


def msg_lembrete(*, servico_nome: str, barbeiro_nome: str, inicio, endereco: str) -> str:
    return (
        f"Lembrete: {servico_nome.lower()} hoje às {formatar_hora(inicio)} "
        f"com {barbeiro_nome}. {endereco}"
    )


def msg_convite(*, nome: str, barbearia_nome: str, link: str) -> str:
    primeiro_nome = nome.split(" ")[0]
    return (
        f"Oi, {primeiro_nome}! Você entrou na equipe da {barbearia_nome}. "
        f"Cria sua senha por aqui pra ver sua agenda:\n\n{link}\n\n"
        f"O link vale por 48 horas."
    )
