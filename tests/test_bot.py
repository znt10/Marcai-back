"""O bot DENTRO do Django: da mensagem recebida ao agendamento gravado e a
resposta que sairia.

A Evolution e' dublada em dois pontos — `app.services.bot._enviar` (o que o
cliente le) e `app.services.bot.enviar_a_equipe` (o que o barbeiro le). O
resto e' de verdade: banco com RLS, `marcar()`, `slots_do_dia`,
`cancelar_publico`.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.bot import processar
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    HorarioTrabalho,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83988887777"


def _barbearia_com_bot(barbearia, *, bot_ativo=True, estado=EstadoInstancia.CONECTADO):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, bot_ativo=bot_ativo,
    )
    return barbearia


def _barbeiro(barbearia, nome="Pedro", papel="BARBEIRO", ordem=0):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True, ordem=ordem,
    )


def _vincular(barbearia, barbeiro, servico):
    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=barbearia.id,
        duracao_min=30, preco_centavos=3500, ativo=True,
    )


def _servico(barbearia, barbeiros, nome="Corte"):
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    for barbeiro in barbeiros:
        _vincular(barbearia, barbeiro, servico)
    return servico


def _aberto_todo_dia(barbearia, barbeiro):
    for dia_semana in range(7):
        HorarioTrabalho.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=barbearia.id, barbeiro_id=barbeiro.id,
            dia_semana=dia_semana, minutos_inicio=0, minutos_fim=1440,
        )


def _cenario_simples(cenario):
    """Um servico e um barbeiro, aberto 24h todo dia: o menor cenario em que
    sempre ha horario, a qualquer hora que a suite rode."""
    b = _barbearia_com_bot(cenario["brutus"])
    pedro = _barbeiro(b)
    _aberto_todo_dia(b, pedro)
    return b, pedro, _servico(b, [pedro])


def _cliente(barbearia, nome="Maria Souza", whatsapp=NUMERO):
    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome, whatsapp=whatsapp,
    )


def _agendamento(barbearia, barbeiro, servico, cliente, inicio):
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico.nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )


def _amanha_redondo():
    return (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        minute=0, second=0, microsecond=0,
    )


class _Conversa:
    """Um cliente conversando. O relogio fica PARADO durante a conversa inteira:
    com um `agora` novo a cada mensagem, o horario oferecido podia passar entre
    a oferta e a confirmacao quando a suite roda perto de uma meia hora."""

    def __init__(self, barbearia, numero=NUMERO, agora=None):
        self.barbearia = barbearia
        self.numero = numero
        self.agora = agora or datetime.now(timezone.utc)
        self.cliente_leu = []
        self.equipe_leu = []

    def diz(self, texto, *, mensagem_id=None):
        def ao_cliente(instancia, numero, mensagem):
            assert instancia == nome_da_instancia(self.barbearia.id)
            assert numero == self.numero
            self.cliente_leu.append(mensagem)
            return f"bot-{uuid.uuid4().hex[:8]}"

        def a_equipe(numero, mensagem):
            self.equipe_leu.append((numero, mensagem))

        with patch("app.services.bot._enviar", side_effect=ao_cliente), patch(
            "app.services.bot.enviar_a_equipe", side_effect=a_equipe
        ):
            return processar(
                str(self.barbearia.id), self.numero, texto,
                mensagem_id or f"msg-{uuid.uuid4().hex}", self.agora,
            )

    @property
    def ultima(self):
        return self.cliente_leu[-1]


def _linha(barbearia, numero=NUMERO):
    with com_barbearia(barbearia.id):
        return ConversaWhatsapp.objects.filter(whatsapp=numero).first()


# ---- menu ----


def test_primeira_mensagem_recebe_o_menu_de_quem_nao_tem_horario(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    assert conversa.diz("oi") == "perguntou"
    assert conversa.ultima.startswith("Oi! Aqui é o atendimento da Brutus.")
    assert "1 - Marcar horário" in conversa.ultima
    assert "Cancelar" not in conversa.ultima
    assert _linha(b).estado == "MENU"


def test_quem_tem_horario_ve_o_horario_no_menu(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    _agendamento(b, pedro, servico, _cliente(b), _amanha_redondo())
    conversa = _Conversa(b)
    conversa.diz("oi")
    assert "Você tem: Pedro," in conversa.ultima
    assert "1 - Marcar outro horário" in conversa.ultima
    assert "2 - Cancelar esse" in conversa.ultima


# ---- marcar ----


def test_marca_do_oi_ao_horario_gravado(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    # Um servico e um barbeiro so': os dois passos sao pulados.
    assert conversa.ultima.startswith("Qual dia?")
    conversa.diz("1")
    assert conversa.ultima.startswith("Horários de")
    conversa.diz("1")
    assert conversa.ultima == "Pra marcar, me diz seu nome:"
    conversa.diz("  João   da Silva ")
    assert conversa.ultima.startswith("Confere:\nCorte com Pedro,")
    assert conversa.diz("1") == "marcou"

    with com_barbearia(b.id):
        [ag] = list(Agendamento.objects.select_related("cliente"))
    assert str(ag.barbeiro_id) == str(pedro.id)
    assert ag.cliente.whatsapp == NUMERO
    assert ag.cliente.nome == "João da Silva"
    assert conversa.ultima.startswith("Fechou, João!")
    assert "brutus." in conversa.ultima and "/agendamento/" in conversa.ultima
    assert [numero for numero, _ in conversa.equipe_leu] == [pedro.whatsapp]
    assert _linha(b).estado == "MENU"
    assert _linha(b).opcoes == []


def test_cliente_conhecido_nao_e_perguntado_o_nome(cenario):
    b, _, _ = _cenario_simples(cenario)
    _cliente(b)
    conversa = _Conversa(b)
    for texto in ("oi", "1", "1", "1"):
        conversa.diz(texto)
    assert conversa.ultima.startswith("Confere:")


def test_dois_servicos_fazem_o_bot_perguntar_qual(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    _servico(b, [pedro], nome="Barba")
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    assert conversa.ultima.startswith("Qual serviço?")
    assert "Barba" in conversa.ultima and "Corte" in conversa.ultima


def test_dois_barbeiros_ganham_o_tanto_faz(cenario):
    b, _, servico = _cenario_simples(cenario)
    zeca = _barbeiro(b, nome="Zeca", ordem=1)
    _aberto_todo_dia(b, zeca)
    _vincular(b, zeca, servico)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    assert conversa.ultima.startswith("Com quem?")
    assert "3 - Tanto faz" in conversa.ultima


def test_horario_pego_entre_oferecer_e_confirmar_volta_para_os_horarios(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    _cliente(b)
    conversa = _Conversa(b)
    for texto in ("oi", "1", "1", "1"):
        conversa.diz(texto)
    inicio = datetime.fromisoformat(_linha(b).rascunho["inicio"])
    _agendamento(b, pedro, servico, _cliente(b, "Mais Rápido", "83900001111"), inicio)

    assert conversa.diz("1") == "perguntou"
    assert conversa.ultima.startswith("Esse horário não está mais disponível.")
    assert _linha(b).estado == "HORA"
    with com_barbearia(b.id):
        assert Agendamento.objects.filter(cliente__whatsapp=NUMERO).count() == 0


# ---- cancelar ----


def test_cancela_o_proprio_horario(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    ag = _agendamento(b, pedro, servico, _cliente(b), _amanha_redondo())
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("2")
    assert conversa.ultima.startswith("Cancelar Pedro,")
    assert conversa.diz("1") == "cancelou"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CANCELADO_CLIENTE"
    assert [numero for numero, _ in conversa.equipe_leu] == [pedro.whatsapp]


def test_nao_cancela_horario_de_outro_numero(cenario):
    """O pior defeito possivel deste bot. A opcao so' existe se o bot a
    ofereceu, mas a casca confere o dono do horario do mesmo jeito: opcao
    guardada nao e' autoridade (spec, secao 3)."""
    b, pedro, servico = _cenario_simples(cenario)
    alheio = _agendamento(
        b, pedro, servico, _cliente(b, "Outra Pessoa", "83911112222"), _amanha_redondo(),
    )
    agora = datetime.now(timezone.utc)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="CONFIRMA_CANCEL",
        opcoes=[{"id": "sim", "rotulo": "Sim, cancelar"}, {"id": "nao", "rotulo": "Não"}],
        rascunho={"codigo": alheio.codigo}, atualizado_em=agora,
    )
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("1") == "nao_e_seu"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=alheio.id).status == "CONFIRMADO"
    assert conversa.equipe_leu == []


def test_cancelar_em_cima_da_hora_respeita_o_prazo(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=30))
    conversa = _Conversa(b, agora=agora)
    conversa.diz("oi")
    conversa.diz("2")
    assert conversa.diz("1") == "fora_do_prazo"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CONFIRMADO"


# ---- lembrete ----


def _parado_no_lembrete(b, ag, agora):
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="AGUARDANDO_LEMBRETE",
        opcoes=[{"id": f"confirmar:{ag.codigo}", "rotulo": "Confirmar"},
                {"id": f"nao_vou:{ag.codigo}", "rotulo": "Não vou conseguir ir"}],
        atualizado_em=agora,
    )


def test_confirmar_o_lembrete_so_responde(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=50))
    _parado_no_lembrete(b, ag, agora)
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("1") == "lembrete_confirmado"
    assert conversa.ultima == "Combinado, te esperamos!"
    assert conversa.equipe_leu == []


def test_nao_vou_avisa_o_barbeiro_e_nao_cancela(cenario):
    """Cancelar ficaria fora do prazo; quem desmarca e' o barbeiro, pelo
    painel. O que importa e' ele saber antes da cadeira ficar vazia."""
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=50))
    _parado_no_lembrete(b, ag, agora)
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("2") == "desistencia_avisada"
    [(numero, texto)] = conversa.equipe_leu
    assert numero == pedro.whatsapp
    assert texto.startswith("Avisou que não vem\nMaria Souza")
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CONFIRMADO"


# ---- guardas ----


def test_mesma_mensagem_duas_vezes_responde_uma(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    assert conversa.diz("oi", mensagem_id="repetida") == "perguntou"
    assert conversa.diz("oi", mensagem_id="repetida") == "duplicada"
    assert len(conversa.cliente_leu) == 1


def test_fora_da_lista_repete_e_na_terceira_oferece_o_zero(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    _servico(b, [pedro], nome="Barba")
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    for _ in range(2):
        assert conversa.diz("9") == "repetiu"
        assert "0 - Falar com a barbearia" not in conversa.ultima
    conversa.diz("9")
    assert conversa.ultima.startswith("Não entendi.")
    assert "Qual serviço?" in conversa.ultima
    assert "0 - Falar com a barbearia" in conversa.ultima
    assert _linha(b).estado == "SERVICO"


def test_zero_chama_o_dono_e_cala_o_bot(cenario):
    b, _, _ = _cenario_simples(cenario)
    dono = _barbeiro(b, nome="Dono", papel="DONO")
    conversa = _Conversa(b)
    conversa.diz("oi")
    assert conversa.diz("0") == "humano"
    [(numero, texto)] = conversa.equipe_leu
    assert numero == dono.whatsapp
    assert "(83) 9 8888-7777" in texto
    lidas = len(conversa.cliente_leu)
    assert conversa.diz("oi?") == "mudo"
    assert len(conversa.cliente_leu) == lidas


def test_conversa_muda_nao_responde(cenario):
    b, _, _ = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO,
        mudo_ate=agora + timedelta(hours=1), atualizado_em=agora,
    )
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("oi") == "mudo"
    assert conversa.cliente_leu == []


@pytest.mark.parametrize(
    "campos", [{"bot_ativo": False}, {"estado": EstadoInstancia.DESCONECTADO}],
)
def test_bot_desligado_ou_desconectado_nao_fala(cenario, campos):
    b = _barbearia_com_bot(cenario["brutus"], **campos)
    conversa = _Conversa(b)
    assert conversa.diz("oi") == "ignorado"
    assert conversa.cliente_leu == []
    assert _linha(b) is None


def test_guarda_o_id_de_cada_resposta(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("9")
    ids = _linha(b).ids_do_bot
    assert len(ids) == 2
    assert all(i.startswith("bot-") for i in ids)
