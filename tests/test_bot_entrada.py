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
              from_me=False, mensagem_id="3A0000000001", citando=False, midia=False,
              context_info=None, source="ios", jid_alt="igual", timestamp=None):
    if midia:
        message = {"imageMessage": {"caption": ""}}
    elif citando:
        message = {"extendedTextMessage": {"text": texto}}
    else:
        message = {"conversation": texto}
    # Formato medido na fatia 0b: `key` traz tambem `remoteJidAlt`,
    # `addressingMode` e `participant`; `data` traz `source` e `messageType`.
    data = {
        "key": {
            "remoteJid": jid,
            "remoteJidAlt": jid if jid_alt == "igual" else jid_alt,
            "addressingMode": "pn",
            "participant": None,
            "fromMe": from_me,
            "id": mensagem_id,
        },
        "message": message,
        "messageType": "imageMessage" if midia else "conversation",
        "source": source,
    }
    if context_info is not None:
        data["contextInfo"] = context_info
    if timestamp is not None:
        data["messageTimestamp"] = timestamp
    return {
        "event": "messages.upsert",
        "instance": nome_da_instancia(barbearia_id),
        "data": data,
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


def test_resposta_citando_no_formato_medido_le_a_conversation():
    """G2 medido na fatia 0b: uma resposta citando chega com o texto em
    `message.conversation`, como mensagem comum — a citacao em si (stanzaId,
    quotedMessage) fica em `data.contextInfo`, um campo separado que
    `ler_mensagem` nunca precisa olhar."""
    corpo = _mensagem(ID, texto="1", context_info={
        "stanzaId": "3A-LEMBRETE", "quotedMessage": {"conversation": "Lembrete: ..."},
    })
    assert ler_mensagem(corpo).texto == "1"


LID = "207843221540943@lid"


def test_chat_lid_le_o_numero_do_remote_jid_alt():
    """Conversa endereçada por `@lid`: o numero de verdade vem em
    `remoteJidAlt`. Descartar esses chats deixaria o cliente sem resposta."""
    corpo = _mensagem(ID, jid=LID, jid_alt="5583988887777@s.whatsapp.net")
    assert ler_mensagem(corpo) == Recebida(ID, NUMERO, "oi", "3A0000000001", False)


@pytest.mark.parametrize("alt", [None, LID, "", "120363025246125486@g.us"])
def test_chat_lid_sem_alt_de_pessoa_continua_descartado(alt):
    assert ler_mensagem(_mensagem(ID, jid=LID, jid_alt=alt)) == "numero"


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


def test_dono_respondendo_num_chat_lid_tambem_cala(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    corpo = _mensagem(
        b.id, from_me=True, jid=LID, jid_alt="5583988887777@s.whatsapp.net",
        mensagem_id="3A-DIGITADO-LID",
    )
    r = _bater(client, corpo)
    assert r.json()["resultado"] == "silenciado"
    assert _linha(b).mudo_ate > datetime.now(timezone.utc) + timedelta(hours=3)


def test_audio_do_dono_tambem_cala(client, cenario):
    """O dono respondeu com audio: ainda e' gente atendendo."""
    b = cenario["brutus"]
    _com_bot(b)
    r = _bater(client, _mensagem(b.id, from_me=True, midia=True))
    assert r.json()["resultado"] == "silenciado"


def test_mensagem_digitada_no_aparelho_com_source_unknown_cala(client, cenario):
    """Medido na fatia 0b: uma mensagem digitada no aparelho da barbearia
    chega com `fromMe: true` e `source: "unknown"`."""
    b = cenario["brutus"]
    _com_bot(b)
    r = _bater(client, _mensagem(b.id, from_me=True, source="unknown"))
    assert r.json()["resultado"] == "silenciado"


def test_instancia_nao_conectada_nao_enfileira(client, cenario):
    """Bot ligado numa instancia que caiu (nao esta CONECTADO) nao pode
    enfileirar — nao ha aparelho para a Evolution entregar a resposta."""
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=nome_da_instancia(b.id),
        estado=EstadoInstancia.DESCONECTADO, bot_ativo=True,
    )
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id))
    assert r.json()["resultado"] == "ignorado:desligado"
    enfileirar.assert_not_called()


def test_eco_da_resposta_do_bot_nao_cala(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, ids_do_bot=["3EB0-DO-BOT"],
    )
    r = _bater(client, _mensagem(b.id, from_me=True, mensagem_id="3EB0-DO-BOT"))
    assert r.json()["resultado"] == "eco"
    assert _linha(b).mudo_ate is None


def test_silenciar_com_a_conversa_presa_nao_trava_o_webhook(cenario, monkeypatch, caplog):
    b = cenario["brutus"]
    monkeypatch.setattr(bot, "BOT_ESPERA_TRAVA_S", 0.2)
    chave = f"{b.id}:{NUMERO}"
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
    try:
        with caplog.at_level("WARNING"):
            resultado = bot.silenciar(str(b.id), NUMERO, "m-x", datetime.now(timezone.utc))
        assert resultado == "ignorado:trava"
        # O numero do cliente NUNCA vai pro log — so' a barbearia e o id da
        # mensagem, que bastam para investigar sem guardar o telefone.
        assert NUMERO not in caplog.text
        assert str(b.id) in caplog.text
        assert "m-x" in caplog.text
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
    """Um 400 aqui faria a Evolution reenviar a mesma foto para sempre.

    O DRF 3.17 nao levanta mais `RequestDataTooBig` ao ler o corpo (ele
    parseia o stream cru): o guarda tem que comparar o `Content-Length` com o
    limite ANTES de tocar em `request.data`."""
    b = cenario["brutus"]
    _com_bot(b)
    corpo = _mensagem(b.id, texto="x" * 4096)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, corpo)
    assert r.status_code == 200
    assert r.json()["resultado"] == "ignorado:grande"
    enfileirar.assert_not_called()


def test_falha_ao_enfileirar_ainda_responde_200(client, cenario):
    """Uma queda do broker ou do banco no meio do webhook nao pode virar 500
    — a Evolution reenviaria o mesmo evento para sempre."""
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR, side_effect=RuntimeError("broker fora do ar")):
        r = _bater(client, _mensagem(b.id))
    assert r.status_code == 200
    assert r.json()["resultado"] == "ignorado:erro"


def test_sem_credencial_continua_401(client, cenario):
    b = cenario["brutus"]
    r = client.post(ROTA, _mensagem(b.id), content_type="application/json",
                    headers={**CABECALHO, "x-marcai-webhook": "errado"})
    assert r.status_code == 401
