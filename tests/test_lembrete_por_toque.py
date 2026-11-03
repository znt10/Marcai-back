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


# ------------------------------------------------------------------- o toque

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import Mock, patch  # noqa: E402

from app.services import whatsapp_meta  # noqa: E402

AGORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
QUEM_TOCOU = "5583977776666"


def _resposta_aceita():
    r = Mock(ok=True, status_code=200, text='{"messages": [{"id": "wamid.X"}]}')
    r.json.return_value = {"messages": [{"id": "wamid.X"}]}
    return r


@pytest.fixture
def meta(monkeypatch, ligado):
    """Meta ligada de mentira: `requests.post` trocado uma vez so' e os
    envios guardados em `meta.posts` (destino, texto)."""
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_NUMERO_ID", "1411744118692075")
    monkeypatch.setenv("META_WHATSAPP_TEMPLATE", "")
    monkeypatch.setenv("META_APP_SECRET", "segredo-do-app")
    with patch.object(whatsapp_meta.requests, "post", return_value=_resposta_aceita()) as post:
        post.enviados = lambda: [
            (c.kwargs["json"]["to"], c.kwargs["json"]["text"]["body"]) for c in post.call_args_list
        ]
        yield post


def _com_zap(barbearia):
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    barbearia.refresh_from_db(using="owner")
    return barbearia


_N = iter(range(10**6))


def _codigo():
    return "k7p2q9" + f"{next(_N):04d}".translate(str.maketrans("0123456789", "abcdefghjk"))


def _agendamento(barbearia, inicio, status="CONFIRMADO", **campos):
    from tenant.models import Agendamento, Barbeiro, Cliente, Servico

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=barbearia.id).first()
    cliente, _ = Cliente.objects.using("owner").get_or_create(
        barbearia_id=barbearia.id, whatsapp="83955554444",
        defaults={"id": str(uuid.uuid4()), "nome": "Ana Souza"},
    )
    servico, _ = Servico.objects.using("owner").get_or_create(
        barbearia_id=barbearia.id, nome="Corte",
        defaults={"id": str(uuid.uuid4()), "duracao_minima_min": 15, "duracao_sugerida_min": 30},
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, codigo=_codigo(),
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status, **campos,
    )


def _recarregar(a):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").get(id=a.id)


def test_toque_grava_e_responde_com_a_confirmacao(cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))

    r = lembrete_por_toque.registrar_pedido(
        lembrete_por_toque.texto_pronto("Brutus", a.codigo), QUEM_TOCOU, AGORA,
    )

    assert r == "pedido"
    a = _recarregar(a)
    assert a.lembrete_pedido_em == AGORA
    assert a.lembrete_para == "83977776666"
    [(para, texto)] = meta.enviados()
    assert para == QUEM_TOCOU
    assert f"/agendamento/{a.codigo}" in texto
    assert texto.startswith("*Brutus*\nFechou, Ana!")


def test_toque_de_celular_antigo_sem_o_nono_digito(cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))
    lembrete_por_toque.registrar_pedido(a.codigo, "558377776666", AGORA)
    assert _recarregar(a).lembrete_para == "83977776666"


def test_toque_repetido_responde_sem_regravar(cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))
    lembrete_por_toque.registrar_pedido(a.codigo, QUEM_TOCOU, AGORA)

    depois = AGORA + timedelta(minutes=5)
    r = lembrete_por_toque.registrar_pedido(a.codigo, "5583911112222", depois)

    assert r == "repetido"
    a = _recarregar(a)
    assert a.lembrete_pedido_em == AGORA
    assert a.lembrete_para == "83977776666"
    assert [para for para, _ in meta.enviados()] == [QUEM_TOCOU, QUEM_TOCOU]


@pytest.mark.parametrize("caso", ["cancelado", "passado", "inexistente", "sem codigo"])
def test_toque_em_cancelado_passado_ou_inexistente_e_ignorado(cenario, meta, caso):
    b = _com_zap(cenario["brutus"])
    if caso == "cancelado":
        a = _agendamento(b, AGORA + timedelta(days=1), status="CANCELADO")
        texto = a.codigo
    elif caso == "passado":
        a = _agendamento(b, AGORA - timedelta(hours=1))
        texto = a.codigo
    elif caso == "inexistente":
        a = _agendamento(b, AGORA + timedelta(days=1))
        texto = "zzzzzzzzzz"
    else:
        a = _agendamento(b, AGORA + timedelta(days=1))
        texto = "oi, quero marcar"

    assert lembrete_por_toque.registrar_pedido(texto, QUEM_TOCOU, AGORA) == "ignorado"
    assert _recarregar(a).lembrete_pedido_em is None
    assert meta.enviados() == []


def test_codigo_de_outra_barbearia_acha_a_barbearia_certa(cenario, meta):
    _com_zap(cenario["brutus"])
    d = _com_zap(cenario["dontony"])
    a = _agendamento(d, AGORA + timedelta(days=1))

    assert lembrete_por_toque.registrar_pedido(
        lembrete_por_toque.texto_pronto("Brutus", a.codigo), QUEM_TOCOU, AGORA,
    ) == "pedido"
    assert _recarregar(a).lembrete_para == "83977776666"
    [(_, texto)] = meta.enviados()
    assert texto.startswith("*Dom Tony*")


def test_toque_nao_liga_o_outro_agendamento_do_mesmo_cliente(cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))
    outro = _agendamento(b, AGORA + timedelta(days=8))
    lembrete_por_toque.registrar_pedido(a.codigo, QUEM_TOCOU, AGORA)
    assert _recarregar(outro).lembrete_pedido_em is None


ROTA_WEBHOOK = "/api/interno/whatsapp/meta"


def _webhook(client, mensagens):
    corpo = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": mensagens}}]}],
    }).encode()
    assinatura = "sha256=" + hmac.new(b"segredo-do-app", corpo, hashlib.sha256).hexdigest()
    return client.post(
        ROTA_WEBHOOK, corpo, content_type="application/json",
        headers={"host": "admin.localhost", "x-hub-signature-256": assinatura},
    )


def test_webhook_com_texto_de_toque_registra(client, cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))

    r = _webhook(client, [
        {"from": QUEM_TOCOU, "type": "text", "text": {"body": f"Quero o lembrete. Código: {a.codigo}"}},
        {"from": QUEM_TOCOU, "type": "image", "image": {"id": "1"}},
    ])

    assert r.status_code == 200
    assert r.json()["resultado"] == "falhas=0 recebidas=2 pedidos=1"
    assert _recarregar(a).lembrete_para == "83977776666"


def test_webhook_com_chave_desligada_nao_registra(client, cenario, meta, monkeypatch):
    monkeypatch.setenv("WHATSAPP_CENTRAL_NUMERO", "")
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))

    r = _webhook(client, [{"from": QUEM_TOCOU, "type": "text", "text": {"body": a.codigo}}])

    assert r.json()["resultado"] == "falhas=0 recebidas=1 pedidos=0"
    assert _recarregar(a).lembrete_pedido_em is None
    assert meta.enviados() == []


def test_webhook_nao_cai_se_o_registro_falhar(client, cenario, meta, caplog):
    with patch.object(lembrete_por_toque, "registrar_pedido", side_effect=RuntimeError("banco")):
        r = _webhook(client, [{"from": QUEM_TOCOU, "type": "text", "text": {"body": "k7p2q9abcd"}}])
    assert r.status_code == 200
    assert r.json()["resultado"] == "falhas=0 recebidas=1 pedidos=0"
    assert "banco" in caplog.text
