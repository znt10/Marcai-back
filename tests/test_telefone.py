import pytest

from tenant.telefone import do_jid, formas_gravadas, nacional_canonico


@pytest.mark.parametrize(
    "jid, esperado",
    [
        ("5583982217869@s.whatsapp.net", "83982217869"),
        # O caso que a fatia 0 mediu: celular sem o nono digito.
        ("558382217869@s.whatsapp.net", "83982217869"),
        # Fixo continua fixo: comeca de 2 a 5, e nao ganha 9 nenhum.
        ("551133334444@s.whatsapp.net", "1133334444"),
    ],
)
def test_jid_de_pessoa_vira_o_numero_gravado(jid, esperado):
    assert do_jid(jid) == esperado


@pytest.mark.parametrize(
    "jid",
    [
        "120363025246125486@g.us",       # grupo
        "status@broadcast",
        "207843221540943@lid",           # identificador sem numero
        "14155550100@s.whatsapp.net",    # fora do Brasil
        "55abc@s.whatsapp.net",
        "",
        None,
    ],
)
def test_o_que_nao_e_pessoa_no_brasil_vira_none(jid):
    assert do_jid(jid) is None


# ---- 10 x 11 digitos ----
# `normalizar` aceita celular antigo de 10 digitos (sem o nono), entao um
# `Cliente` pode estar gravado como `8382217869` enquanto `do_jid` sempre da
# `83982217869`. Sem migracao de dados: quem busca pelo numero aceita as duas.


@pytest.mark.parametrize(
    "numero, esperado",
    [
        ("8382217869", "83982217869"),   # celular sem o nono ganha o 9
        ("83982217869", "83982217869"),  # ja canonico
        ("1133334444", "1133334444"),    # fixo (2 a 5) fica como esta
        ("8352217869", "8352217869"),
    ],
)
def test_nacional_canonico(numero, esperado):
    assert nacional_canonico(numero) == esperado


@pytest.mark.parametrize(
    "numero, esperado",
    [
        ("83982217869", ["83982217869", "8382217869"]),
        ("8382217869", ["83982217869", "8382217869"]),
        # Tirar o 9 daria um fixo (terceiro digito 1): nao e' a mesma pessoa.
        ("83912345678", ["83912345678"]),
        ("1133334444", ["1133334444"]),
    ],
)
def test_formas_gravadas(numero, esperado):
    assert formas_gravadas(numero) == esperado
