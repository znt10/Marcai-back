"""Lembrete por toque pela Evolution (plano 2026-11-06): o cliente manda a
mensagem pronta para o CHIP, e a confirmacao, o lembrete e o cancelamento
saem por ele, sem custo por mensagem. A Meta fica de reserva.

`requests.post` e' trocado UMA vez e separado pela URL: graph.facebook.com e'
a Meta, o resto e' a Evolution.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from app.services import lembrete_por_toque, whatsapp_meta
from test_agendamentos_painel import _barbeiro as _barbeiro_novo, _logar
from test_lembrete_por_toque import AGORA, CENTRAL, _agendamento, _com_zap, _recarregar

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CHIP = "83988010990"
QUEM_ESCREVEU = "5583977776666"
ROTA = "/api/interno/whatsapp/evento"


def _resposta(corpo, ok=True, status=200):
    r = Mock(ok=ok, status_code=status, text=str(corpo))
    r.json.return_value = corpo
    return r


@pytest.fixture
def envios(monkeypatch):
    for nome, valor in {
        "WHATSAPP_PROVEDOR": "meta", "WHATSAPP_CENTRAL_NUMERO": CENTRAL,
        "META_WHATSAPP_TOKEN": "token", "META_WHATSAPP_NUMERO_ID": "1411744118692075",
        "META_WHATSAPP_TEMPLATE": "marcai_aviso",
        "META_TEMPLATE_LEMBRETE": "marcai_lembrete_horario",
        "EVOLUTION_API_URL": "http://evolution:8080", "EVOLUTION_INSTANCE": "Marcai",
        "EVOLUTION_API_KEY": "chave", "WHATSAPP_WEBHOOK_SEGREDO": "segredo",
        "WHATSAPP_WEBHOOK_URL": "http://api:8000/api/interno/whatsapp/evento",
        "LEMBRETE_PELA_EVOLUTION": "1", "WHATSAPP_EVOLUTION_NUMERO": CHIP,
    }.items():
        monkeypatch.setenv(nome, valor)

    class Envios:
        evolution_falha = False
        chamadas: list = []

        def post(self, url, **kw):
            self.chamadas.append((url, kw.get("json") or {}))
            if "graph.facebook.com" in url:
                return _resposta({"messages": [{"id": "wamid.X"}]})
            if self.evolution_falha and "/message/" in url:
                return _resposta({"erro": "fora"}, ok=False, status=500)
            return _resposta({"key": {"id": "E1", "remoteJid": "x@s.whatsapp.net"}})

        def pela_evolution(self, para=None):
            return [j for u, j in self.chamadas if "/message/sendText/" in u
                    and (para is None or j.get("number") == para)]

        def pela_meta(self, para=None):
            return [j for u, j in self.chamadas if "graph.facebook.com" in u
                    and (para is None or j.get("to") == para)]

    e = Envios()
    e.chamadas = []
    with patch.object(whatsapp_meta.requests, "post", side_effect=e.post):
        yield e


def _evento(client, *, texto, jid=f"{QUEM_ESCREVEU}@s.whatsapp.net", alt=None, de_mim=False, instancia="Marcai"):
    chave = {"remoteJid": jid, "fromMe": de_mim, "id": "M1"}
    if alt:
        chave["remoteJidAlt"] = alt
    return client.post(
        ROTA,
        {"event": "messages.upsert", "instance": instancia,
         "data": {"key": chave, "message": {"conversation": texto}}},
        content_type="application/json",
        headers={"host": "admin.localhost", "x-brutus-cliente": "evolution", "x-marcai-webhook": "segredo"},
    )


# ------------------------------------------------------------------- a chave e o botao


def test_botao_aponta_para_o_chip(client, cenario, envios):
    assert lembrete_por_toque.pela_evolution() is True
    assert lembrete_por_toque.link("Brutus", "k7p2q9abcd").startswith(f"https://wa.me/55{CHIP}?text=")
    r = client.get("/api/barbearia", headers={"host": "brutus.localhost", "x-brutus-cliente": "web"})
    assert r.json()["whatsappCentral"] == CHIP


def test_sem_a_chave_o_botao_continua_na_meta(envios, monkeypatch):
    monkeypatch.setenv("LEMBRETE_PELA_EVOLUTION", "")
    assert lembrete_por_toque.pela_evolution() is False
    assert lembrete_por_toque.link("Brutus", "k7p2q9abcd").startswith(f"https://wa.me/55{CENTRAL}?text=")


# ------------------------------------------------------------------- a mensagem chega no chip


def test_mensagem_no_chip_grava_e_responde_pela_evolution(client, cenario, envios):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))

    r = _evento(client, texto=lembrete_por_toque.texto_pronto("Brutus", a.codigo))

    assert r.status_code == 200
    a = _recarregar(a)
    assert a.lembrete_canal == "evolution"
    assert a.lembrete_para == "83977776666"
    [resposta] = envios.pela_evolution(QUEM_ESCREVEU)
    assert resposta["text"].startswith("*Brutus*\nSeu horário foi agendado, Ana!")
    assert envios.pela_meta() == []


def test_lid_usa_o_numero_do_alt(client, cenario, envios):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))
    _evento(client, texto=a.codigo, jid="123456@lid", alt=f"{QUEM_ESCREVEU}@s.whatsapp.net")
    assert _recarregar(a).lembrete_para == "83977776666"


@pytest.mark.parametrize("caso", ["do proprio chip", "grupo", "outra instancia", "chave desligada"])
def test_mensagem_que_nao_e_toque_e_ignorada(client, cenario, envios, monkeypatch, caso):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))
    kw = {"texto": a.codigo}
    if caso == "do proprio chip":
        kw["de_mim"] = True
    elif caso == "grupo":
        kw["jid"] = "123@g.us"
    elif caso == "outra instancia":
        kw["instancia"] = "outra"
    else:
        monkeypatch.setenv("LEMBRETE_PELA_EVOLUTION", "")
    _evento(client, **kw)
    assert _recarregar(a).lembrete_pedido_em is None
    assert envios.pela_evolution() == []


# ------------------------------------------------------------------- os envios


def test_lembrete_de_quem_escreveu_no_chip_sai_pela_evolution(cenario, envios):
    from app.services import lembrete

    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50), lembrete_pedido_em=AGORA - timedelta(days=2),
                 lembrete_para="83977776666", lembrete_canal="evolution")

    assert lembrete.enviar_pendentes(AGORA) == 1

    [msg] = envios.pela_evolution(QUEM_ESCREVEU)
    assert "lembrete" in msg["text"]
    assert envios.pela_meta() == []


def test_chip_fora_do_ar_o_lembrete_cai_na_meta(cenario, envios):
    from app.services import lembrete

    envios.evolution_falha = True
    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50), lembrete_pedido_em=AGORA - timedelta(days=2),
                 lembrete_para="83977776666", lembrete_canal="evolution")

    assert lembrete.enviar_pendentes(AGORA) == 1

    [meta] = envios.pela_meta(QUEM_ESCREVEU)
    assert meta["template"]["name"] == "marcai_lembrete_horario"


def test_pedido_pela_meta_continua_na_meta(cenario, envios):
    from app.services import lembrete

    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50), lembrete_pedido_em=AGORA - timedelta(days=2),
                 lembrete_para="83977776666", lembrete_canal="meta")

    lembrete.enviar_pendentes(AGORA)

    assert envios.pela_evolution() == []
    assert len(envios.pela_meta(QUEM_ESCREVEU)) == 1


def test_barbearia_cancela_quem_escreveu_no_chip_pela_evolution(client, cenario, envios):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=30), lembrete_pedido_em=AGORA,
                     lembrete_para="83977776666", lembrete_canal="evolution")
    host = _logar(client, _barbeiro_novo(b.id, papel="DONO"), b.id)

    r = client.post(f"/api/painel/agendamentos/{a.id}/cancelar",
                    headers={"host": host, "x-brutus-cliente": "web"})

    assert r.status_code == 200, r.content
    assert len(envios.pela_evolution(QUEM_ESCREVEU)) == 1
    assert envios.pela_meta() == []


def test_cliente_cancela_pelo_link_e_o_aviso_sai_pela_evolution(client, cenario, envios):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=2), lembrete_pedido_em=AGORA,
                     lembrete_para="83977776666", lembrete_canal="evolution")
    r = client.post(f"/api/agendamentos/{a.codigo}/cancelar", content_type="application/json",
                    headers={"host": "brutus.localhost", "x-brutus-cliente": "web"})
    assert r.status_code == 200, r.content
    assert len(envios.pela_evolution(QUEM_ESCREVEU)) == 1
    assert envios.pela_meta() == []


# ------------------------------------------------------------------- o chip no admin e o webhook


def test_healthcheck_liga_o_webhook_do_chip(envios):
    from app import tasks

    with patch("app.tasks.estado_da_instancia", return_value="open"), \
         patch("app.tasks.estado_do_chip_da_equipe", return_value="open"):
        tasks.whatsapp_healthcheck()

    [(url, corpo)] = [(u, j) for u, j in envios.chamadas if "/webhook/set/" in u]
    assert url.endswith("/webhook/set/Marcai")
    assert "MESSAGES_UPSERT" in corpo["webhook"]["events"]


def test_admin_mostra_o_chip_com_a_meta_ligada(envios):
    from app.services import whatsapp_central
    from tenant.models import EstadoInstancia

    with patch.object(whatsapp_central, "consultar_estado", return_value=EstadoInstancia.CONECTADO), \
         patch.object(whatsapp_central, "consultar_dono", return_value=f"55{CHIP}@s.whatsapp.net"):
        dados = whatsapp_central.ver_central()

    assert dados["conectado"] is True
    assert dados["numero"] == CHIP
