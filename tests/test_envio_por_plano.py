"""Quem fala com quem, por qual numero.

A regra inteira da fatia cabe em duas linhas, e e' por isso que ela precisa de
teste proprio: **cliente ← numero da barbearia; equipe ← numero central.** O
central nunca fala com cliente, porque um bloqueio de WhatsApp causado por UMA
barbearia derrubaria todas de uma vez — que e' exatamente o que a instancia por
barbearia existe para isolar.

Nada disso aparece em erro de tela: errar aqui manda a mensagem do numero
errado, e o sintoma e' um cliente que nao reconhece quem esta falando com ele.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services import whatsapp
from tenant.models import (
    Barbearia,
    EstadoInstancia,
    MensagemNaoEnviada,
    TipoMensagem,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "central-do-marcai")
    whatsapp.limpar_caches_numero()


def _com_zap(barbearia, estado=EstadoInstancia.CONECTADO, numero_conectado=None):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    barbearia.plano = "COM_ZAP"
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=f"marcai-{barbearia.id}", estado=estado, numero_conectado=numero_conectado,
    )
    return barbearia


def _nao_enviadas(barbearia):
    with com_barbearia(barbearia.id):
        return list(MensagemNaoEnviada.objects.all())


def _instancia_usada(post):
    """A URL do envio termina no nome da instancia: e' ela que diz de qual
    numero a mensagem saiu."""
    return post.call_args.args[0].rsplit("/", 1)[-1]


# ---- cliente ----


def test_com_zap_conectado_sai_pelo_numero_da_barbearia(cenario):
    b = _com_zap(cenario["brutus"])

    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        saiu = whatsapp.enviar_ao_cliente(
            b, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO, cliente_nome="Ana",
        )

    assert saiu is True
    assert _instancia_usada(post) == f"marcai-{b.id}"
    assert _nao_enviadas(b) == []


def test_sem_zap_nao_manda_e_nao_registra(cenario):
    """O cliente desse plano nunca esperou WhatsApp — ele viu a confirmacao na
    tela. Registrar aqui encheria o painel de "nao enviadas" que nao
    representam perda nenhuma."""
    b = cenario["brutus"]

    with patch.object(whatsapp.requests, "post") as post:
        saiu = whatsapp.enviar_ao_cliente(
            b, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO, cliente_nome="Ana",
        )

    assert saiu is False
    assert post.call_count == 0
    assert _nao_enviadas(b) == []


@pytest.mark.parametrize(
    "estado",
    [EstadoInstancia.DESCONECTADO, EstadoInstancia.AGUARDANDO_QR, EstadoInstancia.PENDENTE],
)
def test_com_zap_fora_do_ar_registra_em_vez_de_mandar(cenario, estado):
    """Sem fila e sem fallback pelo central, e as duas metades foram decididas:
    uma confirmacao que chega tres horas depois e pior que nenhuma, e mandar
    pelo central faria o cliente receber de um numero que ele nao conhece."""
    b = _com_zap(cenario["brutus"], estado=estado)

    with patch.object(whatsapp.requests, "post") as post:
        saiu = whatsapp.enviar_ao_cliente(
            b, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO, cliente_nome="Ana",
        )

    assert saiu is False
    assert post.call_count == 0
    registradas = _nao_enviadas(b)
    assert len(registradas) == 1
    assert registradas[0].tipo == TipoMensagem.CONFIRMACAO
    assert registradas[0].cliente_nome == "Ana"


def test_com_zap_sem_linha_registra(cenario):
    """Plano trocado com a Evolution fora do ar: com zap, sem instancia. A
    mensagem nao sai, e o painel tem que dizer isso."""
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    b.plano = "COM_ZAP"

    with patch.object(whatsapp.requests, "post") as post:
        assert whatsapp.enviar_ao_cliente(
            b, "11977778888", "oi", tipo=TipoMensagem.LEMBRETE, cliente_nome="Ana",
        ) is False
    assert post.call_count == 0
    assert len(_nao_enviadas(b)) == 1


def test_registro_falhando_nao_derruba_quem_chamou(cenario, caplog):
    """Esta funcao roda DEPOIS do commit de um agendamento que ja aconteceu.
    Um erro aqui viraria 500 numa tela onde o horario ja esta marcado — o
    cliente leria "deu erro" e apareceria na barbearia no dia certo."""
    b = _com_zap(cenario["brutus"], estado=EstadoInstancia.DESCONECTADO)

    with patch.object(
        whatsapp.MensagemNaoEnviada.objects, "create", side_effect=RuntimeError("boom")
    ):
        with caplog.at_level("ERROR"):
            assert whatsapp.enviar_ao_cliente(
                b, "11977778888", "oi", tipo=TipoMensagem.LEMBRETE, cliente_nome="Ana",
            ) is False
    assert "nao enviada" in caplog.text


def test_a_nao_enviada_fica_na_barbearia_certa(cenario):
    b = _com_zap(cenario["brutus"], estado=EstadoInstancia.DESCONECTADO)
    outra = _com_zap(cenario["dontony"], estado=EstadoInstancia.DESCONECTADO)

    with patch.object(whatsapp.requests, "post"):
        whatsapp.enviar_ao_cliente(
            b, "11977778888", "oi", tipo=TipoMensagem.CONFIRMACAO, cliente_nome="Da Brutus",
        )

    assert [m.cliente_nome for m in _nao_enviadas(b)] == ["Da Brutus"]
    assert _nao_enviadas(outra) == []


# ---- equipe ----


def test_equipe_sai_sempre_pelo_central(cenario):
    b = _com_zap(cenario["brutus"])

    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe("11911112222", "Novo horário")

    # Mesmo com a barbearia tendo numero proprio: o aviso ao barbeiro sai do
    # Marcai, porque quem tem relacao com o Marcai e' o barbeiro.
    assert _instancia_usada(post) == "central-do-marcai"


def test_equipe_e_avisada_tambem_no_plano_sem_zap(cenario):
    """O que a barbearia sem zap nao tem e conversa com CLIENTE. A equipe
    continua recebendo tudo."""
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe("11911112222", "Novo horário")
    assert post.call_count == 1


# ---- equipe no proprio numero da barbearia ----

NUMERO_DA_BARBEARIA = "83999990000"


def _para_a_equipe_da(barbearia, destino, texto="Novo horário"):
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe_da(barbearia.id, destino, texto)
    assert post.call_count == 1
    return _instancia_usada(post)


def test_barbeiro_que_e_o_numero_da_barbearia_recebe_pelo_proprio_numero(cenario):
    """O barbeiro sozinho que conectou o proprio celular como numero da
    barbearia: o aviso cai no "conversar comigo mesmo" dele, e nao num numero
    do Marcai que ele nunca salvou."""
    b = _com_zap(cenario["brutus"], numero_conectado=NUMERO_DA_BARBEARIA)
    assert _para_a_equipe_da(b, NUMERO_DA_BARBEARIA) == f"marcai-{b.id}"


@pytest.mark.parametrize(
    "guardado", ["558399990000@s.whatsapp.net", "558399990000", "5583999990000", "83999990000"],
)
@pytest.mark.parametrize("destino", ["8399990000", "83999990000"])
def test_formas_diferentes_do_mesmo_celular_ainda_casam(cenario, guardado, destino):
    """10, 11 ou 12 digitos, com ou sem JID: e' o mesmo aparelho. A conta
    antiga do WhatsApp vem sem o nono digito e o cadastro pode ter qualquer
    uma das duas formas."""
    b = _com_zap(cenario["brutus"], numero_conectado=guardado)
    assert _para_a_equipe_da(b, destino) == f"marcai-{b.id}"


def test_outro_barbeiro_continua_pelo_central(cenario):
    b = _com_zap(cenario["brutus"], numero_conectado=NUMERO_DA_BARBEARIA)
    assert _para_a_equipe_da(b, "83988887777") == "central-do-marcai"


@pytest.mark.parametrize(
    "estado",
    [EstadoInstancia.DESCONECTADO, EstadoInstancia.AGUARDANDO_QR, EstadoInstancia.PENDENTE],
)
def test_barbearia_fora_do_ar_manda_pelo_central(cenario, estado):
    """Aviso de equipe nao e' mensagem de cliente: com o aparelho fora, o
    central ainda entrega, e o barbeiro nao fica sem saber do horario."""
    b = _com_zap(cenario["brutus"], estado=estado, numero_conectado=NUMERO_DA_BARBEARIA)
    assert _para_a_equipe_da(b, NUMERO_DA_BARBEARIA) == "central-do-marcai"


def test_sem_zap_manda_pelo_central(cenario):
    b = _com_zap(cenario["brutus"], numero_conectado=NUMERO_DA_BARBEARIA)
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="SEM_ZAP")
    assert _para_a_equipe_da(b, NUMERO_DA_BARBEARIA) == "central-do-marcai"


def test_barbearia_desativada_manda_pelo_central(cenario):
    b = _com_zap(cenario["brutus"], numero_conectado=NUMERO_DA_BARBEARIA)
    Barbearia.objects.using("owner").filter(id=b.id).update(ativo=False)
    assert _para_a_equipe_da(b, NUMERO_DA_BARBEARIA) == "central-do-marcai"


def test_barbearia_sem_instancia_manda_pelo_central(cenario):
    """O convite do dono no cadastro de uma barbearia nova: ainda nao existe
    instancia conectada nenhuma."""
    assert _para_a_equipe_da(cenario["brutus"], NUMERO_DA_BARBEARIA) == "central-do-marcai"


# ---- a checagem do numero ----


def test_sem_zap_nao_pergunta_se_o_numero_tem_whatsapp(cenario):
    """Recusar um agendamento por causa de um dado que aquele plano nao usa
    seria perder um horario a troco de nada — o cliente sem zap nao vai
    receber mensagem nenhuma de qualquer forma."""
    with patch.object(whatsapp.requests, "post") as post:
        assert whatsapp.numero_existe(cenario["brutus"], "11977778888", "1.1.1.1") == "indeterminado"
    assert post.call_count == 0


def test_com_zap_pergunta_pela_instancia_da_barbearia(cenario):
    b = _com_zap(cenario["brutus"])
    resposta = _ok()
    resposta.json.return_value = [{"exists": True}]

    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.numero_existe(b, "11977778888", "1.1.1.1") == "existe"

    assert _instancia_usada(post) == f"marcai-{b.id}"


def test_com_zap_desconectado_nao_pergunta_e_deixa_passar(cenario):
    """Indisponibilidade nao e resposta (§10.5): a instancia caida devolve
    `indeterminado`, que deixa o agendamento seguir."""
    b = _com_zap(cenario["brutus"], estado=EstadoInstancia.DESCONECTADO)

    with patch.object(whatsapp.requests, "post") as post:
        assert whatsapp.numero_existe(b, "11977778888", "1.1.1.1") == "indeterminado"
    assert post.call_count == 0


def test_o_cache_do_numero_nao_atravessa_barbearias(cenario):
    """Duas instancias diferentes podem responder diferente sobre o mesmo
    numero — e uma delas pode estar caida. Cache por numero puro faria a
    resposta de uma valer pela outra."""
    b = _com_zap(cenario["brutus"])
    outra = _com_zap(cenario["dontony"])

    sim, nao = _ok(), _ok()
    sim.json.return_value = [{"exists": True}]
    nao.json.return_value = [{"exists": False}]

    with patch.object(whatsapp.requests, "post", side_effect=[sim, nao]):
        assert whatsapp.numero_existe(b, "11977778888", "1.1.1.1") == "existe"
        assert whatsapp.numero_existe(outra, "11977778888", "1.1.1.1") == "nao_existe"


def _ok():
    from unittest.mock import Mock

    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {"key": {"remoteJid": "x"}, "status": "PENDING"}
    return resposta
