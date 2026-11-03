"""Lembrete por toque (spec 2026-11-03): so' recebe WhatsApp quem toca em
"Quero o lembrete" e manda a mensagem pronta ao numero central.

Os envios saem pela Meta com `requests.post` falso, trocado UMA vez so' —
`whatsapp.requests` e `whatsapp_meta.requests` sao o mesmo modulo.
"""

from urllib.parse import quote

import pytest

from app.services import lembrete_por_toque

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CENTRAL = "83988982852"


@pytest.fixture
def ligado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "meta")
    monkeypatch.setenv("WHATSAPP_CENTRAL_NUMERO", CENTRAL)


# ------------------------------------------------------------------- a chave


@pytest.mark.parametrize(("provedor", "numero", "esperado"), [
    ("meta", CENTRAL, True),
    ("meta", "", False),
    ("", CENTRAL, False),
])
def test_ligado_exige_meta_e_numero(monkeypatch, provedor, numero, esperado):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", provedor)
    monkeypatch.setenv("WHATSAPP_CENTRAL_NUMERO", numero)
    assert lembrete_por_toque.ligado() is esperado


def test_numero_central_aceita_mascara(monkeypatch):
    monkeypatch.setenv("WHATSAPP_CENTRAL_NUMERO", " (83) 98898-2852 ")
    assert lembrete_por_toque.numero_central() == CENTRAL


def test_link_monta_o_wa_me_com_o_texto_pronto(ligado):
    assert lembrete_por_toque.link("Brutus", "k7p2q9abcd") == (
        "https://wa.me/5583988982852?text="
        + quote("Quero o lembrete do meu horário na Brutus. Código: k7p2q9abcd")
    )


def test_link_sem_numero_e_none(monkeypatch):
    monkeypatch.delenv("WHATSAPP_CENTRAL_NUMERO", raising=False)
    assert lembrete_por_toque.link("Brutus", "k7p2q9abcd") is None


@pytest.mark.parametrize("texto", [
    "Quero o lembrete do meu horário na Brutus. Código: k7p2q9abcd",
    "K7P2Q9ABCD",
    "Código:k7p2q9abcd",
    "oi\nk7p2q9abcd obrigado",
    "k7p2q9abcd k7p2q9abcd",
])
def test_codigos_no_texto_acha_o_codigo(texto):
    assert lembrete_por_toque.codigos_no_texto(texto) == ["k7p2q9abcd"]


@pytest.mark.parametrize("texto", [
    "oi, tudo bem? lembrete",
    "k7p2q9abcde",  # 11 caracteres: nao e' codigo
    "k7p2q9abc1",  # o 1 nao esta no alfabeto
    "",
])
def test_codigos_no_texto_ignora_o_que_nao_e_codigo(texto):
    assert lembrete_por_toque.codigos_no_texto(texto) == []
