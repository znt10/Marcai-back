from datetime import datetime, timezone

from app.services.mensagens import (
    msg_cancelamento_pela_barbearia,
    msg_confirmacao,
    msg_convite,
)

INICIO = datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc)


def test_msg_confirmacao_leva_o_primeiro_nome_o_dia_a_hora_e_o_link():
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert texto.startswith("Fechou, Maria!")
    # O que a mensagem existe para dizer. Encurtar nao pode custar isto.
    # "13/08", e nao "qui 13 ago": numero se le' de relance na previa da
    # notificacao, dia da semana obriga a traduzir para data antes de decidir.
    assert "13/08" in texto
    assert "08:00" in texto
    assert "Zeca" in texto
    assert texto.endswith("http://x/y")


def test_msg_confirmacao_e_curta_e_sem_endereco():
    """Encurtada a pedido do dono (02/09). O modo de falha que ela ataca: no
    celular, uma mensagem de tres paragrafos chega com um "Ler mais" em cima
    justamente do dia e da hora.

    O endereco saiu — quem marcou acabou de estar na vitrine, que o mostra — e
    passou a viver so' no lembrete, que chega quando a pessoa esta saindo.
    """
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert "Rua Aurora, 88" not in texto
    # Uma linha, uma linha em branco e o link: nada de tres paragrafos.
    assert len(texto.splitlines()) == 3


def test_msg_confirmacao_nunca_perde_o_link_de_cancelar():
    """A linha que NAO se corta por mais que se encurte: sem ela, quem desistiu
    liga pro barbeiro no meio de um corte — ou nao avisa, e o horario fica
    ocupado a toa.
    """
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert "Cancelar" in texto and "http://x/y" in texto


def test_msg_confirmacao_abre_o_servico_com_maiuscula_sem_rebaixar_o_resto():
    """O nome do servico agora ABRE frase. `.capitalize()` do Python nao serve:
    ele rebaixa o resto, e o nome e' do barbeiro, nao nosso.
    """
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="corte de Cabelo",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert "Corte de Cabelo" in texto


def test_msg_cancelamento_pela_barbearia_nao_confunde_com_cancelamento_do_cliente():
    """Separada de proposito: dizer que o CLIENTE cancelou seria mentira na
    cara de quem perdeu o horario porque a barbearia cancelou."""
    texto = msg_cancelamento_pela_barbearia(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88",
    )
    assert texto.startswith("Oi, Maria.")
    # "Cancelamos", na primeira pessoa: quem desmarcou foi a barbearia, e a
    # mensagem tem que assumir isso. A do cliente (`msg_cancelamento`) nao diz
    # quem cancelou justamente porque quem le foi quem cancelou.
    assert "Cancelamos" in texto
    # O pedido de desculpa e o convite a remarcar FICAM, por mais curta que a
    # mensagem seja: e' a diferenca entre um cliente que volta e um que nao.
    assert "Desculpa" in texto
    assert "remarcar" in texto


def test_msg_convite_leva_o_link_uma_vez_e_o_prazo():
    texto = msg_convite(nome="João Pedro", barbearia_nome="Brutus", link="http://x/y")
    assert texto.startswith("Oi, João!")
    assert texto.count("http://x/y") == 1
    assert "48 horas" in texto


# ------------------------------------------------- avisos para o BARBEIRO
#
# Ate aqui o WhatsApp so falava com o CLIENTE: o barbeiro nunca soube que
# alguem marcou com ele sem abrir o painel. Estas duas sao curtas de
# proposito, e sem endereco — ele trabalha la.

AGORA = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)


def test_msg_barbeiro_novo_e_curta_e_nao_leva_endereco():
    from app.services.mensagens import msg_barbeiro_novo

    texto = msg_barbeiro_novo(
        cliente_nome="José Neto", servico_nome="Corte de cabelo",
        inicio=INICIO, agora=AGORA,
    )
    assert texto == "Novo horário\nJosé Neto · hoje 08:00 · Corte de cabelo"


def test_msg_barbeiro_cancelado_diz_que_sumiu_e_nao_que_entrou():
    from app.services.mensagens import msg_barbeiro_cancelado

    texto = msg_barbeiro_cancelado(
        cliente_nome="José Neto", servico_nome="Corte de cabelo",
        inicio=INICIO, agora=AGORA,
    )
    assert texto.startswith("Cancelou")
    assert "José Neto · hoje 08:00 · Corte de cabelo" in texto


def test_msg_do_barbeiro_leva_o_nome_INTEIRO_do_cliente():
    """Ao contrário das mensagens PARA o cliente, que cortam no primeiro nome
    para soar pessoal: o barbeiro precisa distinguir dois Josés da agenda."""
    from app.services.mensagens import msg_barbeiro_novo

    texto = msg_barbeiro_novo(
        cliente_nome="José Neto", servico_nome="Corte", inicio=INICIO, agora=AGORA,
    )
    assert "José Neto" in texto
