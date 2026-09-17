"""POST /api/interno/whatsapp/evento — o que a Evolution bate de volta.

O desenho dos corpos aqui nao e inventado: e o que a Evolution 2.3.7 mandou de
verdade na fatia 0 (nome do evento minusculo e com ponto, `data.qrcode.base64`
ja como `data:image/png;base64,...`, `state` aninhado sob `data`). O unico
campo que NAO foi medido e o `wuid` do `open`, que exige um celular real
escaneando o QR — por isso o codigo o le de forma tolerante e o teste cobre as
duas formas (com e sem).
"""

import uuid

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/interno/whatsapp/evento"
HOST = "admin.localhost"
SEGREDO = "segredo-do-webhook"
# O `x-brutus-cliente` esta aqui porque o `ClienteMiddleware` barra todo POST
# sem ele com 403 — antes de a view rodar. Foi a surpresa da fatia 0, e o
# webhook o manda de verdade, configurado nos `headers` da instancia.
CABECALHO = {"host": HOST, "x-brutus-cliente": "evolution", "x-marcai-webhook": SEGREDO}


@pytest.fixture(autouse=True)
def _segredo_configurado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SEGREDO", SEGREDO)


def _instancia(barbearia, **campos):
    with com_barbearia(barbearia.id):
        return WhatsappInstancia.objects.create(
            id=str(uuid.uuid4()),
            barbearia_id=barbearia.id,
            nome=nome_da_instancia(barbearia.id),
            **campos,
        )


def _recarregar(barbearia):
    with com_barbearia(barbearia.id):
        return WhatsappInstancia.objects.get(barbearia_id=barbearia.id)


def _bater(client, corpo, headers=None):
    return client.post(
        ROTA, corpo, content_type="application/json",
        headers={**CABECALHO, **(headers or {})},
    )


def _conexao(barbearia, state, **extra):
    return {
        "event": "connection.update",
        "instance": nome_da_instancia(barbearia.id),
        "data": {"instance": nome_da_instancia(barbearia.id), "state": state, **extra},
    }


def _qr(barbearia, base64):
    return {
        "event": "qrcode.updated",
        "instance": nome_da_instancia(barbearia.id),
        "data": {"qrcode": {"instance": nome_da_instancia(barbearia.id), "base64": base64}},
    }


# ---- A credencial ----


def test_sem_cabecalho_da_401(client, cenario):
    _instancia(cenario["brutus"])
    r = _bater(client, _conexao(cenario["brutus"], "open"), headers={"x-marcai-webhook": ""})
    assert r.status_code == 401
    assert _recarregar(cenario["brutus"]).estado == EstadoInstancia.PENDENTE


def test_cabecalho_errado_da_401(client, cenario):
    _instancia(cenario["brutus"])
    r = _bater(client, _conexao(cenario["brutus"], "open"), headers={"x-marcai-webhook": "chute"})
    assert r.status_code == 401


def test_segredo_vazio_nega_tudo(client, cenario, monkeypatch):
    """Igual ao CRON_SECRET: sem segredo configurado a rota fecha, em vez de
    virar um jeito publico de mentir sobre o estado do WhatsApp de qualquer
    barbearia."""
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SEGREDO", "")
    _instancia(cenario["brutus"])
    r = _bater(client, _conexao(cenario["brutus"], "open"), headers={"x-marcai-webhook": ""})
    assert r.status_code == 401


def test_segredo_nao_ascii_nao_vira_500(client, cenario):
    """`compare_digest` com `str` nao-ASCII levanta TypeError. Um cabecalho
    forjado tem que virar 401, nunca erro de servidor."""
    _instancia(cenario["brutus"])
    r = _bater(client, _conexao(cenario["brutus"], "open"), headers={"x-marcai-webhook": "ç" * 8})
    assert r.status_code == 401


# ---- connection.update ----


def test_open_conecta_e_limpa_o_qr(client, cenario):
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,velho")

    r = _bater(client, _conexao(b, "open", wuid="5583999990000@s.whatsapp.net"))
    assert r.status_code == 200

    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.CONECTADO
    # Gravado na forma nacional canonica, a mesma de `Barbeiro.whatsapp`.
    assert linha.numero_conectado == "83999990000"
    # QR guardado depois de conectar e' um convite a escanear codigo morto.
    assert linha.qr_base64 is None
    assert linha.desconectado_desde is None


def test_open_de_outro_celular_troca_o_numero_guardado(client, cenario):
    """Regressao: "Trocar de celular" com o aparelho novo. O numero do open
    substitui o antigo, e o `wuid` de conta antiga (sem o nono digito) vira a
    forma de 11 digitos — sem isso o painel mostrava `(83) 9999-0000`, que o
    dono nao reconhece como o celular dele."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.DESCONECTADO, numero_conectado="5583911112222")

    _bater(client, _conexao(b, "open", wuid="558399990000@s.whatsapp.net"))

    assert _recarregar(b).numero_conectado == "83999990000"


def test_open_sem_wuid_conecta_do_mesmo_jeito(client, cenario):
    """O numero e enfeite — quem decide se a mensagem sai e o ESTADO. Perder o
    numero nao pode custar a conexao."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR)

    _bater(client, _conexao(b, "open"))
    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.CONECTADO
    assert linha.numero_conectado is None


@pytest.mark.parametrize("state", ["close", "refused"])
def test_close_desconecta_e_marca_a_hora(client, cenario, state):
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583999990000")

    _bater(client, _conexao(b, state))
    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.DESCONECTADO
    assert linha.desconectado_desde is not None


def test_desconectado_duas_vezes_mantem_a_hora_da_primeira(client, cenario):
    """A faixa do painel diz "desde 14:02". Reescrever a hora a cada evento
    repetido faria ela dizer "desde agora" para sempre, e o dono nunca saberia
    ha quanto tempo esta fora."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.CONECTADO)

    _bater(client, _conexao(b, "close"))
    primeira = _recarregar(b).desconectado_desde

    _bater(client, _conexao(b, "close"))
    assert _recarregar(b).desconectado_desde == primeira


def test_connecting_nao_muda_nada(client, cenario):
    """`connecting` e o intervalo entre pedir o QR e alguem escanear. Trata-lo
    como queda apagaria o QR que o dono esta olhando na tela."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,vivo")

    r = _bater(client, _conexao(b, "connecting"))
    assert r.status_code == 200

    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.AGUARDANDO_QR
    assert linha.qr_base64 == "data:image/png;base64,vivo"


# ---- qrcode.updated ----


def test_qr_novo_e_guardado(client, cenario):
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.PENDENTE)

    _bater(client, _qr(b, "data:image/png;base64,iVBORnovo"))
    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.AGUARDANDO_QR
    assert linha.qr_base64 == "data:image/png;base64,iVBORnovo"


def test_qr_substitui_o_anterior(client, cenario):
    """A Evolution gera um QR novo a cada ~40s enquanto ninguem escaneia. O
    painel tem que mostrar o ULTIMO — o anterior ja nao funciona."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,velho")

    _bater(client, _qr(b, "data:image/png;base64,novo"))
    assert _recarregar(b).qr_base64 == "data:image/png;base64,novo"


def test_qr_sem_base64_limpa_o_guardado_em_vez_de_ignorar(client, cenario):
    """Um evento de QR sem base64 (por exemplo quando a Evolution bate o
    limite de QRs) nao traz codigo novo. Se o corpo fosse so ignorado, o
    painel continuaria mostrando o QR antigo, ja morto — o dono nunca
    conseguiria reconectar. Limpar o campo faz o proximo `ver()` pedir um QR
    novo de verdade."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,velho")

    corpo = {
        "event": "qrcode.updated",
        "instance": nome_da_instancia(b.id),
        "data": {"qrcode": {"instance": nome_da_instancia(b.id)}},
    }
    r = _bater(client, corpo)

    assert r.status_code == 200
    linha = _recarregar(b)
    assert linha.qr_base64 is None
    assert linha.estado == EstadoInstancia.AGUARDANDO_QR


# ---- o que nao e para ca ----


def test_instancia_desconhecida_responde_200_sem_efeito(client, cenario):
    """200 e nao 404, de proposito: a Evolution REENVIA o que nao foi aceito.
    Uma instancia que nao e nossa (ou de uma barbearia ja apagada) viraria um
    laco de reentrega para sempre."""
    _instancia(cenario["brutus"])
    corpo = {
        "event": "connection.update",
        "instance": f"marcai-{uuid.uuid4()}",
        "data": {"state": "open"},
    }
    r = _bater(client, corpo)
    assert r.status_code == 200
    assert _recarregar(cenario["brutus"]).estado == EstadoInstancia.PENDENTE


def test_nome_fora_do_padrao_responde_200_sem_efeito(client, cenario):
    _instancia(cenario["brutus"])
    r = _bater(client, {"event": "connection.update", "instance": "brutus", "data": {"state": "open"}})
    assert r.status_code == 200


def test_evento_de_outro_tipo_responde_200_sem_efeito(client, cenario):
    """A assinatura pede dois eventos, mas quem garante isso e a configuracao
    do lado de la — e configuracao muda sem avisar."""
    b = cenario["brutus"]
    _instancia(b, estado=EstadoInstancia.CONECTADO)
    corpo = {"event": "messages.upsert", "instance": nome_da_instancia(b.id), "data": {}}
    r = _bater(client, corpo)
    assert r.status_code == 200
    assert _recarregar(b).estado == EstadoInstancia.CONECTADO


def test_corpo_sem_nada_dentro_responde_200(client, cenario):
    r = _bater(client, {})
    assert r.status_code == 200


def test_um_evento_nao_mexe_na_outra_barbearia(client, cenario):
    """A prova de que o webhook escreve DENTRO do tenant: ele descobre a
    barbearia por um nome que veio da rede, e escrever no tenant errado aqui
    seria o estado do WhatsApp de uma barbearia aparecendo em outra."""
    b, outra = cenario["brutus"], cenario["dontony"]
    _instancia(b, estado=EstadoInstancia.AGUARDANDO_QR)
    _instancia(outra, estado=EstadoInstancia.AGUARDANDO_QR)

    _bater(client, _conexao(b, "open"))

    assert _recarregar(b).estado == EstadoInstancia.CONECTADO
    assert _recarregar(outra).estado == EstadoInstancia.AGUARDANDO_QR
