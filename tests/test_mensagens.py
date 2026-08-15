from datetime import datetime, timezone

from app.services.mensagens import (
    msg_cancelamento_pela_barbearia,
    msg_confirmacao,
    msg_convite,
)

INICIO = datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc)


def test_msg_confirmacao_leva_o_primeiro_nome_o_link_e_o_endereco():
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert texto.startswith("Fechou, Maria!")
    assert "corte" in texto  # minusculo — nao grita o nome do servico
    assert "Rua Aurora, 88" in texto
    assert texto.endswith("http://x/y")


def test_msg_cancelamento_pela_barbearia_nao_confunde_com_cancelamento_do_cliente():
    """Separada de proposito: dizer que o CLIENTE cancelou seria mentira na
    cara de quem perdeu o horario porque a barbearia cancelou."""
    texto = msg_cancelamento_pela_barbearia(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88",
    )
    assert texto.startswith("Oi, Maria.")
    assert "Precisamos cancelar" in texto


def test_msg_convite_leva_o_link_uma_vez_e_o_prazo():
    texto = msg_convite(nome="João Pedro", barbearia_nome="Brutus", link="http://x/y")
    assert texto.startswith("Oi, João!")
    assert texto.count("http://x/y") == 1
    assert "48 horas" in texto
