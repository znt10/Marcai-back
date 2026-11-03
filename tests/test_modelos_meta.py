"""Um modelo da Meta por mensagem (03/11): confirmacao com o botao "Quero
lembrete 1h antes", lembrete e cancelamento pela barbearia, cada um com as
quebras de linha no texto fixo — o parametro do `marcai_aviso` nao aceita
quebra, e tudo saia numa linha so', depois de "Atualização do seu
agendamento".

Com a conversa aberta (o cliente acabou de tocar), sai texto normal.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from app.services import lembrete_por_toque, whatsapp_meta
from test_lembrete_por_toque import (
    AGORA,
    CENTRAL,
    QUEM_TOCOU,
    _agendamento,
    _com_zap,
    _marcar,
    _webhook,
)
from test_agendamentos_painel import _barbeiro as _barbeiro_novo, _logar

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CLIENTE = "5583955554444"
DIGITADO = "5511977778888"


def _resposta(ok=True, corpo=None, status=200):
    corpo = corpo or {"messages": [{"id": "wamid.X"}]}
    r = Mock(ok=ok, status_code=status, text=str(corpo))
    r.json.return_value = corpo
    return r


@pytest.fixture
def meta(monkeypatch):
    """Meta ligada como em producao: `marcai_aviso` configurado, lembrete por
    toque ligado e os tres modelos novos preenchidos."""
    for nome, valor in {
        "WHATSAPP_PROVEDOR": "meta", "WHATSAPP_CENTRAL_NUMERO": CENTRAL,
        "META_WHATSAPP_TOKEN": "token", "META_WHATSAPP_NUMERO_ID": "1411744118692075",
        "META_WHATSAPP_TEMPLATE": "marcai_aviso", "META_APP_SECRET": "segredo-do-app",
        "META_TEMPLATE_CONFIRMACAO": "marcai_confirmado",
        "META_TEMPLATE_LEMBRETE": "marcai_lembrete_1h",
        "META_TEMPLATE_CANCELADO": "marcai_cancelado",
    }.items():
        monkeypatch.setenv(nome, valor)
    with patch.object(whatsapp_meta.requests, "post", return_value=_resposta()) as post:
        post.corpos = lambda para=None: [
            c.kwargs["json"] for c in post.call_args_list
            if para is None or c.kwargs["json"]["to"] == para
        ]
        yield post


def _parametros(corpo):
    corpo_do_modelo = next(c for c in corpo["template"]["components"] if c["type"] == "body")
    return [p["text"] for p in corpo_do_modelo["parameters"]]


# ------------------------------------------------------------------- lembrete


def test_lembrete_sai_pelo_modelo_proprio(cenario, meta):
    from app.services import lembrete
    from tenant.models import Barbearia

    b = _com_zap(cenario["brutus"])
    Barbearia.objects.using("owner").filter(id=b.id).update(endereco="")
    inicio = AGORA + timedelta(minutes=50)  # 12:50 em Sao Paulo
    _agendamento(b, inicio, lembrete_pedido_em=AGORA - timedelta(days=2), lembrete_para="83977776666")

    assert lembrete.enviar_pendentes(AGORA) == 1

    [corpo] = meta.corpos()
    assert corpo["to"] == QUEM_TOCOU
    assert corpo["template"]["name"] == "marcai_lembrete_1h"
    # Endereco vazio vira traco: a Meta recusa parametro vazio.
    assert _parametros(corpo) == [
        "Brutus", "Corte", "12:50", "Barbeiro da Brutus", "—", "(11) 9 9999-8888",
    ]


def test_sem_a_variavel_o_lembrete_continua_no_aviso(cenario, meta, monkeypatch):
    from app.services import lembrete

    monkeypatch.setenv("META_TEMPLATE_LEMBRETE", "")
    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50),
                 lembrete_pedido_em=AGORA - timedelta(days=2), lembrete_para="83977776666")

    lembrete.enviar_pendentes(AGORA)

    [corpo] = meta.corpos()
    assert corpo["template"]["name"] == "marcai_aviso"


def test_modelo_recusado_cai_no_aviso(cenario, meta, caplog):
    """Variavel preenchida antes da aprovacao (132001) nao pode calar o
    lembrete."""
    from app.services import lembrete

    meta.side_effect = [
        _resposta(False, {"error": {"code": 132001, "message": "Template does not exist"}}, 404),
        _resposta(),
    ]
    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50),
                 lembrete_pedido_em=AGORA - timedelta(days=2), lembrete_para="83977776666")

    assert lembrete.enviar_pendentes(AGORA) == 1

    nomes = [c["template"]["name"] for c in meta.corpos()]
    assert nomes == ["marcai_lembrete_1h", "marcai_aviso"]
    assert "132001" in caplog.text


def test_lembrete_de_quem_tocou_ha_pouco_sai_como_texto(cenario, meta):
    """Tocou ha menos de 23h: a conversa esta aberta, sai texto com as
    quebras de linha e sem o "Atualização do seu agendamento"."""
    from app.services import lembrete

    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50),
                 lembrete_pedido_em=AGORA - timedelta(hours=5), lembrete_para="83977776666",
                 lembrete_tocado_em=AGORA - timedelta(hours=5))

    lembrete.enviar_pendentes(AGORA)

    [corpo] = meta.corpos()
    assert corpo["type"] == "text"
    assert corpo["text"]["body"].startswith("*Brutus — lembrete: corte hoje às 12:50*\n")


def test_lembrete_prometido_sem_toque_nao_sai_como_texto(cenario, meta):
    """Marcado antes da chave: nasce pedido, mas ninguem escreveu. Texto
    fora da janela seria aceito e sumiria."""
    from app.services import lembrete

    b = _com_zap(cenario["brutus"])
    _agendamento(b, AGORA + timedelta(minutes=50),
                 lembrete_pedido_em=AGORA - timedelta(hours=2), lembrete_para="83955554444")

    lembrete.enviar_pendentes(AGORA)

    [corpo] = meta.corpos()
    assert corpo["template"]["name"] == "marcai_lembrete_1h"


def test_toque_reabre_a_janela(cenario, meta):
    from tenant.models import Agendamento

    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))
    lembrete_por_toque.registrar_pedido(a.codigo, QUEM_TOCOU, AGORA)
    depois = AGORA + timedelta(hours=3)
    lembrete_por_toque.registrar_pedido(a.codigo, QUEM_TOCOU, depois)
    a = Agendamento.objects.using("owner").get(id=a.id)
    assert a.lembrete_pedido_em == AGORA
    assert a.lembrete_tocado_em == depois


# ------------------------------------------------------------------- confirmacao


def test_confirmacao_do_painel_tem_o_botao_com_o_codigo(client, cenario, meta):
    codigo = _marcar(client, _com_zap(cenario["brutus"]), pelo_painel=True)

    [corpo] = meta.corpos(DIGITADO)
    assert corpo["template"]["name"] == "marcai_confirmado"
    parametros = _parametros(corpo)
    assert parametros[0] == "Brutus"
    assert parametros[1].startswith("Fechou, Ana! ")
    assert parametros[2] == "(11) 9 9999-8888"
    assert parametros[3].endswith(f"/agendamento/{codigo}")
    botao = next(c for c in corpo["template"]["components"] if c["type"] == "button")
    assert botao["sub_type"] == "quick_reply"
    assert botao["index"] == "0"
    assert botao["parameters"] == [{"type": "payload", "payload": f"lembrete:{codigo}"}]


def test_confirmacao_do_painel_sem_a_chave_continua_no_aviso(client, cenario, meta, monkeypatch):
    """Sem o lembrete por toque o botao prometeria o que ja vem sozinho."""
    monkeypatch.setenv("WHATSAPP_CENTRAL_NUMERO", "")
    _marcar(client, _com_zap(cenario["brutus"]), pelo_painel=True)
    [corpo] = meta.corpos(DIGITADO)
    assert corpo["template"]["name"] == "marcai_aviso"


def test_resposta_ao_toque_sai_como_texto(cenario, meta):
    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, AGORA + timedelta(days=1))

    lembrete_por_toque.registrar_pedido(a.codigo, QUEM_TOCOU, AGORA)

    [corpo] = meta.corpos()
    assert corpo["type"] == "text"
    assert corpo["text"]["body"].startswith("*Brutus*\nFechou, Ana!")


def test_toque_no_botao_do_modelo_registra_o_pedido(client, cenario, meta):
    from tenant.models import Agendamento

    b = _com_zap(cenario["brutus"])
    a = _agendamento(b, datetime.now(timezone.utc) + timedelta(days=1))

    r = _webhook(client, [{
        "from": QUEM_TOCOU, "type": "button",
        "button": {"payload": f"lembrete:{a.codigo}", "text": "Quero lembrete 1h antes"},
    }])

    assert r.json()["resultado"] == "falhas=0 recebidas=1 pedidos=1"
    assert Agendamento.objects.using("owner").get(id=a.id).lembrete_para == "83977776666"


# ------------------------------------------------------------------- cancelamento


def test_cancelamento_pela_barbearia_sai_pelo_modelo(client, cenario, meta):
    b = _com_zap(cenario["brutus"])
    inicio = AGORA + timedelta(days=30)
    a = _agendamento(b, inicio)
    host = _logar(client, _barbeiro_novo(b.id, papel="DONO"), b.id)

    r = client.post(
        f"/api/painel/agendamentos/{a.id}/cancelar",
        headers={"host": host, "x-brutus-cliente": "web"},
    )
    assert r.status_code == 200, r.content

    [corpo] = meta.corpos(CLIENTE)
    assert corpo["template"]["name"] == "marcai_cancelado"
    parametros = _parametros(corpo)
    assert parametros[:3] == ["Ana", "Brutus", "corte"]
    assert parametros[4] == "12:00"
    assert parametros[5] == "(11) 9 9999-8888"


def test_parametro_com_quebra_de_linha_e_achatado():
    """O parametro de modelo nao aceita quebra (132018), em nenhum modelo."""
    modelo = whatsapp_meta.Modelo("META_TEMPLATE_LEMBRETE", ["Rua A\nCentro", ""])
    assert modelo.parametros_prontos() == ["Rua A · Centro", "—"]
