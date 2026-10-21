"""A forma padrao da chave Pix (funcao pura)."""

import pytest

from app.services.pix_do_barbeiro import forma_padrao

UUID = "123E4567-E89B-12D3-A456-426614174000"


@pytest.mark.parametrize("tipo,entrada,saida", [
    ("CPF", "529.982.247-25", "52998224725"),
    ("CPF", " 52998224725 ", "52998224725"),
    ("CNPJ", "11.222.333/0001-81", "11222333000181"),
    ("CELULAR", "(83) 99999-1234", "+5583999991234"),
    ("CELULAR", "83999991234", "+5583999991234"),
    ("CELULAR", "+55 83 99999-1234", "+5583999991234"),
    ("CELULAR", "5583999991234", "+5583999991234"),
    ("CELULAR", "(83) 3222-1234", "+558332221234"),
    ("CELULAR", "55999991234", "+5555999991234"),  # DDD 55 (RS), sem o 55 do pais
    ("EMAIL", "  Fulano@Exemplo.COM ", "fulano@exemplo.com"),
    ("ALEATORIA", UUID, UUID.lower()),
])
def test_aceita_e_padroniza(tipo, entrada, saida):
    assert forma_padrao(tipo, entrada) == (saida, None)


@pytest.mark.parametrize("tipo,entrada", [
    ("CPF", "529.982.247-26"),
    ("CPF", "111.111.111-11"),
    ("CPF", "5299822472"),
    ("CNPJ", "11.222.333/0001-82"),
    ("CNPJ", "00000000000000"),
    ("CELULAR", "(83) 9999-123"),
    ("CELULAR", "(03) 99999-1234"),
    ("CELULAR", "83899991234"),
    ("CELULAR", ""),
    ("EMAIL", "sem-arroba"),
    ("EMAIL", "@x.com"),
    ("EMAIL", "a@"),
    ("EMAIL", "a@b@c.com"),
    ("EMAIL", "a" * 80 + "@x.com"),
    ("ALEATORIA", "nao-e-uuid"),
    ("", "52998224725"),
    ("OUTRO", "52998224725"),
])
def test_recusa_com_frase(tipo, entrada):
    chave, erro = forma_padrao(tipo, entrada)
    assert chave is None and erro


def test_frase_do_cpf():
    assert forma_padrao("CPF", "1")[1] == "Esse CPF não é válido."
