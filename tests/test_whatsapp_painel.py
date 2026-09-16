"""GET /api/painel/whatsapp e POST /api/painel/whatsapp/desconectar.

A regra que estes casos existem para prender: **o QR e' so do dono; a FAIXA e
de todo mundo.** As duas metades importam. Um barbeiro que visse o QR poderia
ligar o WhatsApp da barbearia ao proprio celular e passar a receber as
mensagens de todos os clientes. Um barbeiro que nao visse a faixa ficaria a
tarde inteira sem entender por que ninguem confirma.
"""

import uuid

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Barbearia,
    Barbeiro,
    EstadoInstancia,
    MensagemNaoEnviada,
    WhatsappInstancia,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/painel/whatsapp"


def _barbeiro(barbearia_id, papel="BARBEIRO"):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"{papel} teste",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia):
    from app.services.sessao import COOKIE_SESSAO, emitir

    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia.id, papel=barbeiro.papel, tv=barbeiro.token_version,
    )
    return f"{barbearia.slug}.localhost"


def _com_zap(barbearia, estado=EstadoInstancia.CONECTADO, **campos):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    barbearia.plano = "COM_ZAP"
    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, **campos,
    )


def test_sem_sessao_da_401(client, cenario):
    r = client.get(ROTA, headers={"host": "brutus.localhost"})
    assert r.status_code == 401


def test_sem_zap_responde_o_plano_e_mais_nada(client, cenario):
    """A tela existe nos dois planos — no sem zap ela e' a resposta a pergunta
    "cade o WhatsApp?", e a resposta e' "voce nao comprou"."""
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "DONO")
    host = _logar(client, dono, b)

    corpo = client.get(ROTA, headers={"host": host}).json()
    assert corpo["plano"] == "SEM_ZAP"
    assert corpo["estado"] is None
    assert corpo["qrBase64"] is None
    assert corpo["naoEnviadas"] == 0


def test_dono_ve_o_qr(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,oQR")
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    corpo = client.get(ROTA, headers={"host": host}).json()
    assert corpo["plano"] == "COM_ZAP"
    assert corpo["estado"] == "AGUARDANDO_QR"
    assert corpo["qrBase64"] == "data:image/png;base64,oQR"


def test_barbeiro_ve_o_estado_mas_nunca_o_qr(client, cenario):
    """A metade que protege: com o QR na mao, um barbeiro liga o WhatsApp da
    barbearia ao proprio celular e passa a receber a conversa de todo cliente.
    O ESTADO ele ve, porque e dele que sai a faixa."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64="data:image/png;base64,oQR")
    host = _logar(client, _barbeiro(b.id), b)

    corpo = client.get(ROTA, headers={"host": host}).json()
    assert corpo["estado"] == "AGUARDANDO_QR"
    assert corpo["qrBase64"] is None


def test_conectado_mostra_o_numero(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583999990000")
    host = _logar(client, _barbeiro(b.id), b)

    corpo = client.get(ROTA, headers={"host": host}).json()
    assert corpo["estado"] == "CONECTADO"
    assert corpo["numeroConectado"] == "5583999990000"


def test_conta_as_mensagens_que_nao_sairam(client, cenario):
    """O numero que faz o dono descobrir a queda pelo prejuizo, e nao so pela
    faixa."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.DESCONECTADO)
    for nome in ("Ana", "Bruno"):
        MensagemNaoEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, tipo="CONFIRMACAO", cliente_nome=nome,
        )
    # Da OUTRA barbearia: nao pode entrar nesta conta.
    MensagemNaoEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=cenario["dontony"].id,
        tipo="CONFIRMACAO", cliente_nome="De outra",
    )
    host = _logar(client, _barbeiro(b.id), b)

    assert client.get(ROTA, headers={"host": host}).json()["naoEnviadas"] == 2


def test_dono_sem_qr_guardado_pede_um_novo(client, cenario):
    """O caminho de quem abre a tela depois de o ultimo QR ter expirado — sem
    isto, a tela mostraria um vazio permanente e o dono nunca conectaria."""
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.DESCONECTADO)
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    with patch(
        "app.services.whatsapp_painel.pedir_qr", return_value="data:image/png;base64,fresco"
    ) as pedir:
        corpo = client.get(ROTA, headers={"host": host}).json()

    assert pedir.call_count == 1
    assert corpo["qrBase64"] == "data:image/png;base64,fresco"


def test_barbeiro_sem_qr_guardado_nao_pede_nada(client, cenario):
    """Pedir um QR que o barbeiro nem vai ver seria gastar uma chamada de rede
    para produzir um segredo que ninguem pediu — e, pior, guardar esse segredo
    na linha."""
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.DESCONECTADO)
    host = _logar(client, _barbeiro(b.id), b)

    with patch("app.services.whatsapp_painel.pedir_qr") as pedir:
        client.get(ROTA, headers={"host": host})
    assert pedir.call_count == 0


def test_pendente_nao_pede_qr(client, cenario):
    """`PENDENTE` e "a instancia ainda nao existe la". Pedir o QR dela traria
    404 — quem resolve isso e a conferencia periodica, criando a instancia."""
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.PENDENTE)
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    with patch("app.services.whatsapp_painel.pedir_qr") as pedir:
        client.get(ROTA, headers={"host": host})
    assert pedir.call_count == 0


# ---- desconectar (trocar de celular) ----


def test_dono_desconecta(client, cenario):
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583999990000")
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    with patch("app.services.whatsapp_painel.desconectar_aparelho", return_value=True) as sair:
        r = client.post(
            f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"},
        )
    assert r.status_code == 200
    assert sair.call_count == 1


def test_barbeiro_nao_desconecta(client, cenario):
    """403 e nao 404: quem chegou aqui tem sessao valida e ja sabe que nao e
    dono — esconder a rota nao esconderia nada que ele nao soubesse."""
    from unittest.mock import patch

    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)
    host = _logar(client, _barbeiro(b.id), b)

    with patch("app.services.whatsapp_painel.desconectar_aparelho") as sair:
        r = client.post(
            f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"},
        )
    assert r.status_code == 403
    assert sair.call_count == 0


def test_desconectar_sem_zap_da_422(client, cenario):
    """Nao ha aparelho para desligar. 422 e nao 404: a rota existe, o pedido e
    que nao faz sentido nesse plano."""
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    r = client.post(f"{ROTA}/desconectar", headers={"host": host, "x-brutus-cliente": "web"})
    assert r.status_code == 422


def test_uma_barbearia_nao_ve_o_whatsapp_da_outra(client, cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583111112222")
    _com_zap(outra, estado=EstadoInstancia.DESCONECTADO, numero_conectado="5511999998888")
    host = _logar(client, _barbeiro(b.id, "DONO"), b)

    corpo = client.get(ROTA, headers={"host": host}).json()
    assert corpo["numeroConectado"] == "5583111112222"
