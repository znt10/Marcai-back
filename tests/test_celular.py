"""A validacao ESTRITA de celular — a que o agendamento publico usa.

`normalizar` continua valendo para o login e para o cadastro da equipe: la um
fixo e' um numero de contato legitimo. Aqui nao: o produto inteiro depende de
mandar WhatsApp, e fixo nunca tem WhatsApp. Duas regras porque sao duas
perguntas diferentes.
"""
import pytest

from tenant.telefone import celular, normalizar


@pytest.mark.parametrize("entrada", [
    "83982217869",
    "(83) 9 8221-7869",
    "+55 83 98221-7869",
    "5583982217869",
])
def test_aceita_celular_de_verdade_em_qualquer_forma_digitada(entrada):
    assert celular(entrada) == "83982217869"


def test_recusa_fixo_ainda_que_normalizar_aceite():
    """O controle negativo do par: `normalizar` DEIXA passar, `celular` nao.
    Sem os dois lados, o teste nao distingue "a regra nova pegou" de "a regra
    velha ja pegava".
    """
    fixo = "8332217869"
    assert normalizar(fixo) == fixo
    assert celular(fixo) is None


def test_recusa_ddd_que_nao_existe_no_brasil():
    """20, 23, 25, 26, 29 e 30 caem na faixa 11..99 que `normalizar` aceita, e
    nenhum deles e' DDD. Sao os erros de digitacao mais comuns: trocar 21 por
    20, 83 por 30."""
    for ddd in ("20", "23", "25", "26", "29", "30", "60", "70", "72", "76", "78", "90"):
        numero = f"{ddd}982217869"
        assert normalizar(numero) == numero, f"{ddd}: normalizar devia aceitar"
        assert celular(numero) is None, f"{ddd} nao e' DDD e passou"


def test_aceita_os_ddds_das_pontas():
    for ddd in ("11", "99", "83", "21", "68"):
        assert celular(f"{ddd}982217869") == f"{ddd}982217869"


@pytest.mark.parametrize("ruim", [
    "8398221786",     # falta um digito para celular (vira fixo de 10)
    "839822178690",   # sobra
    "83882217869",    # 11 digitos sem o 9 na frente
    "",
    None,
    "nao e numero",
])
def test_recusa_o_que_nao_e_celular(ruim):
    assert celular(ruim) is None
