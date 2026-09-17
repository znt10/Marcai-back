"""O lembrete que ja existia, respondido pelo bot."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import bot
from app.services.lembrete import enviar_pendentes
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83988887777"
ENVIAR = "app.services.bot._enviar"


def _cenario(cenario, *, bot_ativo=True):
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=nome_da_instancia(b.id),
        estado=EstadoInstancia.CONECTADO, bot_ativo=bot_ativo,
    )
    pedro = Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Pedro",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel="BARBEIRO", ativo=True,
    )
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Maria Souza", whatsapp=NUMERO,
    )
    agora = datetime.now(timezone.utc)
    inicio = agora + timedelta(minutes=30)
    ag = Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=pedro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )
    return b, ag, agora


def _linha(b):
    with com_barbearia(b.id):
        return ConversaWhatsapp.objects.filter(whatsapp=NUMERO).first()


def test_com_bot_o_lembrete_sai_com_opcoes_e_para_a_conversa(cenario):
    b, ag, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE") as enviar:
        assert enviar_pendentes(agora) == 1
    instancia, numero, texto = enviar.call_args.args
    assert instancia == nome_da_instancia(b.id)
    assert numero == NUMERO
    assert texto.startswith("Lembrete:")
    assert texto.endswith("1 - Confirmar\n2 - Não vou conseguir ir")
    linha = _linha(b)
    assert linha.estado == "AGUARDANDO_LEMBRETE"
    assert [o["id"] for o in linha.opcoes] == [f"confirmar:{ag.codigo}", f"nao_vou:{ag.codigo}"]
    assert linha.ids_do_bot == ["3EB0-LEMBRETE"]


def test_responder_1_confirma(cenario):
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE"):
        enviar_pendentes(agora)
    respostas = []
    with patch(ENVIAR, side_effect=lambda i, n, t: respostas.append(t) or "3EB0-R"), patch(
        "app.services.bot.enviar_a_equipe"
    ):
        desfecho = bot.processar(str(b.id), NUMERO, "1", "3A-RESPOSTA", agora + timedelta(minutes=5))
    assert desfecho == "lembrete_confirmado"
    assert respostas == ["Combinado, te esperamos!"]


def test_responder_fora_da_faixa_repete_a_pergunta_do_lembrete(cenario):
    """Achado da Tarefa 6: `_executar` repete `pergunta_anterior or ""` no
    Repetir. Se a linha do lembrete nao gravar `pergunta`, um "9" aqui vira
    "Nao entendi" seguido de nada."""
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE"):
        enviar_pendentes(agora)
    respostas = []
    with patch(ENVIAR, side_effect=lambda i, n, t: respostas.append(t) or "3EB0-R"):
        desfecho = bot.processar(str(b.id), NUMERO, "9", "3A-RESPOSTA", agora + timedelta(minutes=5))
    assert desfecho == "repetiu"
    assert len(respostas) == 1
    assert "1 - Confirmar" in respostas[0]
    assert "2 - Não vou conseguir ir" in respostas[0]


def test_o_eco_do_lembrete_nao_cala_o_bot(cenario):
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE"):
        enviar_pendentes(agora)
    assert bot.silenciar(str(b.id), NUMERO, "3EB0-LEMBRETE", agora) == "eco"
    assert _linha(b).mudo_ate is None


def test_conversa_em_andamento_recebe_o_lembrete_sem_opcoes(cenario):
    """Quem esta escolhendo horario agora nao pode ter a conversa trocada
    por baixo: o proximo "1" dele confirmaria o lembrete em vez da hora."""
    b, _, agora = _cenario(cenario)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="HORA",
        opcoes=[{"id": "outro_dia", "rotulo": "Outro dia"}],
        atualizado_em=agora - timedelta(minutes=2),
    )
    with patch(ENVIAR, return_value="3EB0-LEMBRETE") as enviar:
        enviar_pendentes(agora)
    assert "1 - Confirmar" not in enviar.call_args.args[2]
    linha = _linha(b)
    assert linha.estado == "HORA"
    assert linha.ids_do_bot == ["3EB0-LEMBRETE"]


def test_sem_bot_o_lembrete_segue_o_caminho_de_sempre(cenario):
    b, _, agora = _cenario(cenario, bot_ativo=False)
    with patch("app.services.lembrete.enviar_ao_cliente") as ao_cliente, patch(ENVIAR) as enviar:
        assert enviar_pendentes(agora) == 1
    ao_cliente.assert_called_once()
    enviar.assert_not_called()
    assert _linha(b) is None


def test_falha_no_envio_nao_grava_estado_como_se_tivesse_entregue(cenario):
    """Se `_enviar` nao devolve id, o cliente nao viu opcoes nenhuma na tela:
    a conversa nao pode ficar esperando um "1"/"2" que nunca vai fazer
    sentido (mesma regra de `_gravar`, Tarefa 6 — sem entrega, sem avanco)."""
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value=None):
        assert enviar_pendentes(agora) == 1
    assert _linha(b) is None
