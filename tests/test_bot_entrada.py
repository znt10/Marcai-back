"""POST /api/interno/whatsapp/evento com `messages.upsert`.

Num numero de uso real, 40 de 42 eventos eram de grupo e quase todos com
midia (spec, secao 11). O descarte tem que ser cedo e barato, e o que sobra
tem que chegar ao worker sem o webhook esperar resposta nenhuma.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.db import connections
from django.test import override_settings

from app.services import bot
from app.services.bot_entrada import Recebida, ler_mensagem
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import Barbearia, ConversaWhatsapp, EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/interno/whatsapp/evento"
SEGREDO = "segredo-do-webhook"
CABECALHO = {"host": "admin.localhost", "x-brutus-cliente": "evolution", "x-marcai-webhook": SEGREDO}
ENFILEIRAR = "app.services.bot_entrada.enfileirar"
NUMERO = "83988887777"


@pytest.fixture(autouse=True)
def _segredo(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SEGREDO", SEGREDO)


def _mensagem(barbearia_id, *, texto="oi", jid="5583988887777@s.whatsapp.net",
              from_me=False, mensagem_id="3A0000000001", citando=False, midia=False):
    if midia:
        message = {"imageMessage": {"caption": ""}}
    elif citando:
        message = {"extendedTextMessage": {"text": texto}}
    else:
        message = {"conversation": texto}
    return {
        "event": "messages.upsert",
        "instance": nome_da_instancia(barbearia_id),
        "data": {"key": {"remoteJid": jid, "fromMe": from_me, "id": mensagem_id}, "message": message},
    }


def _com_bot(barbearia, bot_ativo=True):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome_da_instancia(barbearia.id),
        estado=EstadoInstancia.CONECTADO, bot_ativo=bot_ativo,
    )


def _bater(client, corpo):
    return client.post(ROTA, corpo, content_type="application/json", headers=CABECALHO)


def _linha(barbearia):
    with com_barbearia(barbearia.id):
        return ConversaWhatsapp.objects.filter(whatsapp=NUMERO).first()


# ---- leitura pura ----

ID = str(uuid.uuid4())


def test_texto_simples_vira_recebida():
    assert ler_mensagem(_mensagem(ID)) == Recebida(ID, NUMERO, "oi", "3A0000000001", False)


def test_resposta_citando_le_o_texto_do_outro_campo():
    """Quem responde o lembrete segurando a mensagem manda o texto em
    `extendedTextMessage` — ler so' `conversation` ignoraria justamente essas."""
    assert ler_mensagem(_mensagem(ID, texto="1", citando=True)).texto == "1"


def test_midia_chega_sem_texto():
    assert ler_mensagem(_mensagem(ID, midia=True)).texto is None


def test_propria_barbearia_e_marcada():
    assert ler_mensagem(_mensagem(ID, from_me=True)).do_proprio_numero is True


@pytest.mark.parametrize("corpo, motivo", [
    ("nao e dict", "corpo"),
    ({"event": "connection.update"}, "evento"),
    ({**_mensagem(ID), "instance": "outra-coisa"}, "instancia"),
    ({**_mensagem(ID), "data": "x"}, "dados"),
    (_mensagem(ID, jid="120363025246125486@g.us"), "grupo"),
    (_mensagem(ID, jid="207843221540943@lid"), "numero"),
    (_mensagem(ID, mensagem_id=""), "id"),
])
def test_descartes(corpo, motivo):
    assert ler_mensagem(corpo) == motivo


# ---- pela rota ----


def test_texto_com_bot_ligado_vai_para_a_fila(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id))
    assert r.status_code == 200
    assert r.json()["resultado"] == "enfileirado"
    enfileirar.assert_called_once_with(Recebida(str(b.id), NUMERO, "oi", "3A0000000001", False))


def test_bot_desligado_nao_enfileira_nem_grava(client, cenario):
    b = cenario["brutus"]
    _com_bot(b, bot_ativo=False)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id))
    assert r.json()["resultado"] == "ignorado:desligado"
    enfileirar.assert_not_called()
    assert _linha(b) is None


def test_grupo_e_descartado_com_200(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, jid="120363025246125486@g.us"))
    assert r.status_code == 200
    assert r.json()["resultado"] == "ignorado:grupo"
    enfileirar.assert_not_called()


def test_midia_de_cliente_nao_enfileira(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, midia=True))
    assert r.json()["resultado"] == "ignorado:sem_texto"
    enfileirar.assert_not_called()


def test_dono_respondendo_pelo_celular_cala_o_bot(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, from_me=True, mensagem_id="3A-DIGITADO"))
    assert r.json()["resultado"] == "silenciado"
    enfileirar.assert_not_called()
    assert _linha(b).mudo_ate > datetime.now(timezone.utc) + timedelta(hours=3)


def test_audio_do_dono_tambem_cala(client, cenario):
    """O dono respondeu com audio: ainda e' gente atendendo."""
    b = cenario["brutus"]
    _com_bot(b)
    r = _bater(client, _mensagem(b.id, from_me=True, midia=True))
    assert r.json()["resultado"] == "silenciado"


def test_eco_da_resposta_do_bot_nao_cala(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, ids_do_bot=["3EB0-DO-BOT"],
    )
    r = _bater(client, _mensagem(b.id, from_me=True, mensagem_id="3EB0-DO-BOT"))
    assert r.json()["resultado"] == "eco"
    assert _linha(b).mudo_ate is None


def test_silenciar_com_a_conversa_presa_nao_trava_o_webhook(cenario, monkeypatch):
    b = cenario["brutus"]
    monkeypatch.setattr(bot, "BOT_ESPERA_TRAVA_S", 0.2)
    chave = f"{b.id}:{NUMERO}"
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
    try:
        assert bot.silenciar(str(b.id), NUMERO, "x", datetime.now(timezone.utc)) == "ignorado:trava"
    finally:
        with connections["owner"].cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])


def test_evento_de_conexao_continua_no_caminho_de_sempre(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    corpo = {"event": "connection.update", "instance": nome_da_instancia(b.id),
             "data": {"state": "close"}}
    with patch("app.api.v1.views.interno.aplicar_evento", return_value="desconectado") as aplicar:
        r = _bater(client, corpo)
    assert r.json()["resultado"] == "desconectado"
    aplicar.assert_called_once()


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=512)
def test_evento_grande_demais_ainda_responde_200(client, cenario):
    """Um 400 aqui faria a Evolution reenviar a mesma foto para sempre."""
    b = cenario["brutus"]
    _com_bot(b)
    corpo = _mensagem(b.id, texto="x" * 4096)
    with patch(ENFILEIRAR):
        r = _bater(client, corpo)
    assert r.status_code == 200


def test_sem_credencial_continua_401(client, cenario):
    b = cenario["brutus"]
    r = client.post(ROTA, _mensagem(b.id), content_type="application/json",
                    headers={**CABECALHO, "x-marcai-webhook": "errado"})
    assert r.status_code == 401
