import pytest

from tenant.telefone import do_jid


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
