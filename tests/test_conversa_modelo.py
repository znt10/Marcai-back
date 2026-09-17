"""O que o banco garante sobre a conversa do bot, antes de qualquer regra."""

import uuid

import pytest
from django.db import IntegrityError

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import ConversaWhatsapp, WhatsappInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _conversa(barbearia, whatsapp="83911110000"):
    return ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, whatsapp=whatsapp,
    )


def test_o_bot_nasce_desligado(cenario):
    """Ninguem acorda com um robo atendendo o numero do proprio negocio."""
    b = cenario["brutus"]
    linha = WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=nome_da_instancia(b.id),
    )
    assert linha.bot_ativo is False


def test_conversa_nasce_no_menu_sem_nada_guardado(cenario):
    c = _conversa(cenario["brutus"])
    assert c.estado == "MENU"
    assert c.opcoes == []
    assert c.rascunho == {}
    assert c.tentativas == 0
    assert c.ids_do_bot == []
    assert c.mudo_ate is None


def test_o_mesmo_numero_e_uma_conversa_so_por_barbearia(cenario):
    _conversa(cenario["brutus"])
    with pytest.raises(IntegrityError):
        _conversa(cenario["brutus"])


def test_o_mesmo_numero_em_duas_barbearias_sao_duas_conversas(cenario):
    _conversa(cenario["brutus"])
    _conversa(cenario["dontony"])
