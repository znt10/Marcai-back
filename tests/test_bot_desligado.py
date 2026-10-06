"""O bot de agendamento desligado (etapa 1 do numero central, spec
2026-10-06). O codigo dele fica inteiro — volta no plano de agendar pelo
WhatsApp com a API oficial —, mas nada chega nele enquanto `BOT_DISPONIVEL`
for False."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import bot_entrada
from tenant import config


def test_os_dois_interruptores_nascem_desligados():
    assert config.BOT_DISPONIVEL is False
    assert config.WHATSAPP_POR_BARBEARIA is False


def test_receber_ignora_antes_de_consultar_o_banco():
    """Sem marca de banco: se `receber` consultasse qualquer tabela, o
    pytest-django recusaria o acesso e o teste quebraria."""
    corpo = {
        "event": "messages.upsert",
        "instance": f"marcai-{uuid.uuid4()}",
        "data": {
            "key": {"remoteJid": "5583988887777@s.whatsapp.net", "id": "A1", "fromMe": False},
            "message": {"conversation": "oi"},
        },
    }
    assert bot_entrada.receber(corpo, datetime.now(timezone.utc)) == "ignorado:desligado"


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_ligar_o_bot_e_recusado_sem_tocar_na_evolution(cenario):
    """Com zap e conectada — o unico estado em que, antes, ligar passava."""
    from app.services import whatsapp_painel
    from tenant.models import Barbearia, EstadoInstancia, WhatsappInstancia

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    b.plano = "COM_ZAP"
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=f"marcai-{b.id}",
        estado=EstadoInstancia.CONECTADO,
    )

    with patch.object(whatsapp_painel, "aplicar_assinatura", return_value=True) as aplicar:
        assert whatsapp_painel.ligar_bot(b, True) is False
    aplicar.assert_not_called()


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_lembrete_nao_vai_pelo_bot_mesmo_com_bot_ligado_na_linha(cenario, monkeypatch):
    """Uma linha de instancia velha com `bot_ativo=True` (sobra de antes do
    comando que desliga tudo) nao pode puxar o lembrete para o bot."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    from app.services import lembrete
    from tenant.models import (
        Agendamento, Barbearia, Barbeiro, Cliente, EstadoInstancia, Servico,
        WhatsappInstancia,
    )

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=f"marcai-{b.id}",
        estado=EstadoInstancia.CONECTADO, bot_ativo=True,
    )
    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=30, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Ana", whatsapp="11977778888",
    )
    agora = datetime.now(timezone.utc)
    inicio = agora + timedelta(minutes=30)
    Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    with patch("app.services.lembrete.enviar_ao_cliente") as ao_cliente, patch(
        "app.services.bot.enviar_lembrete_pelo_bot"
    ) as pelo_bot:
        assert lembrete.enviar_pendentes(agora) == 1
    ao_cliente.assert_called_once()
    pelo_bot.assert_not_called()
