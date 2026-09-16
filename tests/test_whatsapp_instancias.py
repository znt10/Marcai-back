"""A conversa com a Evolution sobre a instancia DA BARBEARIA.

A Evolution e simulada com `patch.object(..., "requests")`, o mesmo padrao do
`tests/test_whatsapp.py` — e as respostas simuladas nao sao inventadas: os
status e os corpos foram medidos contra a Evolution 2.3.7 de verdade na fatia
0 (403 "already in use" no create repetido, 404 no `connectionState` de
instancia que nao existe, `state` aninhado sob `instance`).
"""

import uuid
from unittest.mock import Mock, patch

import pytest
import requests as requests_lib

from app.services import whatsapp_instancias as wi
from tenant.models import EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _evolution_configurada(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("WHATSAPP_WEBHOOK_URL", "http://api:8000/api/interno/whatsapp/evento")
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SEGREDO", "segredo-do-webhook")
    monkeypatch.setenv("DOMINIO_BASE", "usemarcai.online")


def _linha(barbearia, **campos):
    """A linha nasce no cadastro (dentro da transacao do admin) e o servico so
    a ENCONTRA — por isso todo caso de teste a cria antes."""
    with com_barbearia(barbearia.id):
        return WhatsappInstancia.objects.create(
            id=str(uuid.uuid4()),
            barbearia_id=barbearia.id,
            nome=wi.nome_da_instancia(barbearia.id),
            **campos,
        )


def _recarregar(barbearia):
    with com_barbearia(barbearia.id):
        return WhatsappInstancia.objects.get(barbearia_id=barbearia.id)


# ---- O nome, que e a chave dos dois lados ----


def test_nome_e_id_fazem_a_volta():
    ident = str(uuid.uuid4())
    assert wi.barbearia_id_do_nome(wi.nome_da_instancia(ident)) == ident


@pytest.mark.parametrize("nome", ["brutus", "", "marcai-", "outra-marcai-abc", "marcai-nao-e-uuid"])
def test_nome_de_fora_nao_vira_barbearia(nome):
    """O webhook e publico na rede interna: um nome que nao siga o padrao tem
    que virar `None` e nao um id meio montado. O `marcai-nao-e-uuid` esta na
    lista porque o prefixo sozinho nao prova nada — sem conferir o formato do
    uuid, ele viraria uma consulta com lixo dentro."""
    assert wi.barbearia_id_do_nome(nome) is None


# ---- garantir_instancia ----


def test_garantir_cria_na_evolution_e_aplica_o_webhook(cenario):
    barbearia = cenario["brutus"]
    _linha(barbearia)

    with patch.object(wi.requests, "post", return_value=Mock(ok=True, status_code=201)) as post:
        wi.garantir_instancia(barbearia)

    criar, webhook = post.call_args_list
    nome = wi.nome_da_instancia(barbearia.id)

    assert criar.args[0] == "http://evolution:8080/instance/create"
    assert criar.kwargs["json"]["instanceName"] == nome
    assert criar.kwargs["json"]["qrcode"] is True
    assert criar.kwargs["json"]["integration"] == "WHATSAPP-BAILEYS"
    assert criar.kwargs["headers"]["apikey"] == "chave"

    assert webhook.args[0] == f"http://evolution:8080/webhook/set/{nome}"
    corpo = webhook.kwargs["json"]["webhook"]
    assert corpo["url"] == "http://api:8000/api/interno/whatsapp/evento"
    assert corpo["enabled"] is True
    assert corpo["base64"] is True
    assert sorted(corpo["events"]) == ["CONNECTION_UPDATE", "QRCODE_UPDATED"]
    # Os TRES cabecalhos, e cada um por um motivo diferente, todos medidos na
    # fatia 0: o `Host` faz o pedido passar pelo ALLOWED_HOSTS e pelo
    # TenantMiddleware como host de admin; o `x-brutus-cliente` passa pelo
    # ClienteMiddleware, que barra POST sem ele com 403 antes de a view rodar;
    # o `x-marcai-webhook` e a unica credencial de verdade.
    assert corpo["headers"]["Host"] == "admin.usemarcai.online"
    assert corpo["headers"]["x-marcai-webhook"] == "segredo-do-webhook"
    assert corpo["headers"]["x-brutus-cliente"] == "evolution"


def test_garantir_tira_a_linha_de_pendente(cenario):
    """`PENDENTE` quer dizer "a Evolution ainda nao sabe que isto existe". Sair
    dele e o que impede a conferencia periodica de recriar a mesma instancia a
    cada cinco minutos."""
    barbearia = cenario["brutus"]
    _linha(barbearia)

    with patch.object(wi.requests, "post", return_value=Mock(ok=True, status_code=201)):
        wi.garantir_instancia(barbearia)

    assert _recarregar(barbearia).estado == EstadoInstancia.AGUARDANDO_QR


def test_garantir_e_idempotente_quando_o_nome_ja_esta_em_uso(cenario):
    """403 "already in use" nao e falha: e a Evolution dizendo que o trabalho
    ja estava feito. O webhook e reaplicado mesmo assim — e o unico caminho
    que conserta uma instancia viva cujo webhook aponta para o lugar errado."""
    barbearia = cenario["brutus"]
    _linha(barbearia)

    ja_existe = Mock(
        ok=False,
        status_code=403,
        text='{"status":403,"error":"Forbidden","response":{"message":["This name \\"x\\" is already in use."]}}',
    )
    ok = Mock(ok=True, status_code=200)

    with patch.object(wi.requests, "post", side_effect=[ja_existe, ok]) as post:
        wi.garantir_instancia(barbearia)

    assert "/webhook/set/" in post.call_args_list[1].args[0]
    assert _recarregar(barbearia).estado == EstadoInstancia.AGUARDANDO_QR


def test_garantir_com_evolution_fora_do_ar_deixa_pendente_e_nao_lanca(cenario, caplog):
    """A Evolution cair nao pode derrubar o cadastro da barbearia. A linha fica
    `PENDENTE` e a conferencia periodica termina o servico no proximo tique."""
    barbearia = cenario["brutus"]
    _linha(barbearia)

    with patch.object(wi.requests, "post", side_effect=requests_lib.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            wi.garantir_instancia(barbearia)

    assert _recarregar(barbearia).estado == EstadoInstancia.PENDENTE
    assert "instancia" in caplog.text.lower()


def test_garantir_sem_linha_no_banco_nao_lanca(cenario):
    """Chamada solta, sem a linha que o cadastro cria: nada a fazer, e nada que
    justifique estourar em cima de quem chamou."""
    with patch.object(wi.requests, "post") as post:
        wi.garantir_instancia(cenario["brutus"])
    assert post.call_count == 0


def test_garantir_sem_evolution_configurada_nao_fala_com_a_rede(cenario, monkeypatch):
    """O modo de desenvolver sem WhatsApp nenhum, igual ao `enviar_texto`."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    _linha(cenario["brutus"])

    with patch.object(wi.requests, "post") as post:
        wi.garantir_instancia(cenario["brutus"])

    assert post.call_count == 0
    assert _recarregar(cenario["brutus"]).estado == EstadoInstancia.PENDENTE


# ---- apagar_instancia ----


def test_apagar_desliga_na_evolution_e_some_com_a_linha(cenario):
    barbearia = cenario["brutus"]
    _linha(barbearia, estado=EstadoInstancia.CONECTADO)
    nome = wi.nome_da_instancia(barbearia.id)

    with patch.object(wi.requests, "delete", return_value=Mock(ok=True, status_code=200)) as dele:
        wi.apagar_instancia(barbearia)

    urls = [c.args[0] for c in dele.call_args_list]
    # Logout ANTES do delete: apagar sem deslogar deixa a sessao pendurada no
    # celular do dono, e o WhatsApp dele continua achando que ha um aparelho
    # conectado que ninguem mais controla.
    assert urls == [
        f"http://evolution:8080/instance/logout/{nome}",
        f"http://evolution:8080/instance/delete/{nome}",
    ]
    with com_barbearia(barbearia.id):
        assert not WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).exists()


def test_apagar_com_evolution_fora_do_ar_ainda_apaga_a_linha(cenario, caplog):
    """A linha vai embora mesmo assim, e isso e uma escolha: o que esta
    acontecendo aqui e uma barbearia saindo do plano com zap, e travar a
    troca de plano numa indisponibilidade da Evolution deixaria o produto
    preso num estado que ninguem pediu. O custo — uma instancia orfa la — fica
    no log para alguem limpar."""
    barbearia = cenario["brutus"]
    _linha(barbearia, estado=EstadoInstancia.CONECTADO)

    with patch.object(wi.requests, "delete", side_effect=requests_lib.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            wi.apagar_instancia(barbearia)

    with com_barbearia(barbearia.id):
        assert not WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).exists()
    assert "orfa" in caplog.text.lower() or "apagar" in caplog.text.lower()


# ---- consultar_estado ----


@pytest.mark.parametrize(
    "corpo,esperado",
    [
        ('{"instance":{"instanceName":"x","state":"open"}}', EstadoInstancia.CONECTADO),
        ('{"instance":{"instanceName":"x","state":"close"}}', EstadoInstancia.DESCONECTADO),
        ('{"state":"open"}', EstadoInstancia.CONECTADO),
    ],
)
def test_consultar_estado_normaliza(corpo, esperado):
    with patch.object(wi.requests, "get", return_value=Mock(ok=True, status_code=200, text=corpo)):
        assert wi.consultar_estado("marcai-x") == esperado


def test_consultar_estado_connecting_nao_decide_nada():
    """`connecting` e o intervalo entre pedir o QR e alguem escanear. Devolver
    `DESCONECTADO` aqui faria a faixa do painel piscar toda vez que o dono
    abrisse a tela do QR."""
    corpo = '{"instance":{"instanceName":"x","state":"connecting"}}'
    with patch.object(wi.requests, "get", return_value=Mock(ok=True, status_code=200, text=corpo)):
        assert wi.consultar_estado("marcai-x") is None


def test_consultar_estado_404_volta_para_pendente():
    """A instancia sumiu do lado de la (volume perdido, apagada a mao). Voltar
    para `PENDENTE` e o que faz a conferencia periodica recria-la — qualquer
    outro estado a deixaria morta para sempre."""
    corpo = '{"status":404,"error":"Not Found","response":{"message":["The \\"x\\" instance does not exist"]}}'
    with patch.object(wi.requests, "get", return_value=Mock(ok=False, status_code=404, text=corpo)):
        assert wi.consultar_estado("marcai-x") == EstadoInstancia.PENDENTE


def test_consultar_estado_com_falha_de_rede_nao_decide_nada(caplog):
    with patch.object(wi.requests, "get", side_effect=requests_lib.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            assert wi.consultar_estado("marcai-x") is None


# ---- pedir_qr ----


def test_pedir_qr_devolve_o_base64():
    corpo = {"pairingCode": None, "code": "2@abc", "base64": "data:image/png;base64,iVBOR"}
    resposta = Mock(ok=True, status_code=200)
    resposta.json.return_value = corpo
    with patch.object(wi.requests, "get", return_value=resposta) as get:
        assert wi.pedir_qr("marcai-x") == "data:image/png;base64,iVBOR"
    assert get.call_args.args[0] == "http://evolution:8080/instance/connect/marcai-x"


def test_pedir_qr_sem_base64_devolve_none():
    """Instancia ja conectada responde sem `base64` — nao ha QR a mostrar, e
    isso nao e erro."""
    resposta = Mock(ok=True, status_code=200)
    resposta.json.return_value = {"instance": {"state": "open"}}
    with patch.object(wi.requests, "get", return_value=resposta):
        assert wi.pedir_qr("marcai-x") is None


def test_pedir_qr_com_falha_de_rede_devolve_none(caplog):
    with patch.object(wi.requests, "get", side_effect=requests_lib.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            assert wi.pedir_qr("marcai-x") is None
