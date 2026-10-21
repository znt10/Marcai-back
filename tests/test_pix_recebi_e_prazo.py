"""O "recebi" e o prazo do Pix (P4): confirmar na mao, a varredura que libera o
horario vencido, a corrida entre as duas e o aviso de devolucao quando se
cancela um horario pago. Fluxo de verdade (RLS, tres conexoes); so' o envio do
WhatsApp e' simulado."""
import uuid
from datetime import datetime, timedelta, timezone as fuso
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.db.utils import OperationalError
from django.utils import timezone

from app.services.sessao import COOKIE_SESSAO, emitir
from test_pix_no_agendamento import (  # noqa: F401  (fixtures e ajudantes do P3)
    CABECALHO,
    HOST,
    _agendamento,
    _barbeiro,
    _chamar_marcar,
    _cobrancas,
    _inicio,
    _marcar_no_site,
    PIX_DO_DONO,
    _sem_whatsapp_de_verdade,
    envios,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)


@pytest.fixture
def avisos():
    """Os envios feitos pelos servicos novos (varredura, recebi, devolucao)."""
    with patch("app.services.pix_agendamento.enviar_ao_cliente") as exp_cliente, patch(
        "app.services.pix_agendamento.enviar_a_equipe_da"
    ) as devolucao, patch("app.services.confirmar_pagamento.enviar_ao_cliente") as conf_cliente, patch(
        "app.services.confirmar_pagamento.enviar_a_equipe_da"
    ) as conf_equipe, patch("app.services.confirmar_pagamento.lista_do_dia.avisar_mudanca") as lista:

        class Avisos:
            def expirados(self):
                return [(c.args[1], c.args[2]) for c in exp_cliente.call_args_list]

            def confirmacoes(self):
                return [(c.args[1], c.args[2]) for c in conf_cliente.call_args_list]

            def devolucoes(self):
                return [(c.args[1], c.args[2]) for c in devolucao.call_args_list]

            def avisos_curtos(self):
                return [(c.args[1], c.args[2]) for c in conf_equipe.call_args_list]

        a = Avisos()
        a.lista = lista
        a.cliente_conf = conf_cliente
        yield a


def _agora():
    return datetime.now(fuso.utc)


def _vencer(minutos=1):
    """Faz o prazo de toda cobranca aberta ter passado ha' `minutos`."""
    from tenant.models import Cobranca

    Cobranca.objects.using("owner").filter(status="ABERTA").update(
        expira_em=_agora() - timedelta(minutes=minutos),
    )


def _varrer(**kw):
    from app.services.pix_agendamento import expirar_vencidos

    return expirar_vencidos(_agora(), **kw)


def _aguardando(client, b, barbeiro, servico, minutos=10 * 60, whatsapp="11977778888"):
    r = _marcar_no_site(client, barbeiro, servico, minutos, whatsapp=whatsapp)
    assert r.status_code == 201
    return _agendamento(r.json()["codigo"])


def _sessao(client, barbeiro, b, papel="BARBEIRO"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=b.id, papel=papel, tv=0)


def _recebi(client, a, host=HOST):
    return client.post(
        f"/api/painel/agendamentos/{a.id}/recebi", headers={"host": host, **CABECALHO},
    )


def _status_cobranca():
    return [c.status for c in _cobrancas()]


# ---- o recebi

def test_recebi_confirma_o_agendamento_e_paga_a_cobranca(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)

    antes = _agora()
    r = _recebi(client, a)

    assert r.status_code == 200 and r.json() == {"ok": True}
    a = _agendamento(a.codigo)
    assert a.status == "CONFIRMADO"
    assert a.lembrete_enviado_em is None  # daqui a 30 dias: o lembrete e' do cron
    [c] = _cobrancas()
    assert (c.status, c.como_foi_paga) == ("PAGA", "MANUAL")
    assert c.paga_em >= antes
    # Os avisos de um CONFIRMADO de hoje: confirmacao ao cliente e a lista do dia.
    [(numero, texto)] = avisos.confirmacoes()
    assert numero == "11977778888" and "Fechou" in texto and f"/agendamento/{a.codigo}" in texto
    avisos.lista.assert_called_once()
    assert avisos.lista.call_args.kwargs["novos"] == [(a.id, a.inicio)]


def test_recebi_dentro_da_janela_do_lembrete_ja_nasce_avisado(client, cenario, envios, avisos):
    """A confirmacao que sai agora JA e' o lembrete: a mesma regra de quem nasce
    confirmado perto da hora."""
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    from tenant.models import Agendamento

    perto = _agora() + timedelta(hours=1)
    Agendamento.objects.using("owner").filter(id=a.id).update(
        inicio=perto, fim=perto + timedelta(minutes=30),
    )
    _sessao(client, barbeiro, b)
    assert _recebi(client, a).status_code == 200
    assert _agendamento(a.codigo).lembrete_enviado_em is not None


def test_avisa_o_barbeiro_com_a_mensagem_curta_quando_a_fila_esta_fora(client, cenario, envios, avisos):
    from app.services import lista_do_dia

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    avisos.lista.return_value = lista_do_dia.FILA_FORA
    _sessao(client, barbeiro, b)
    assert _recebi(client, a).status_code == 200
    [(numero, texto)] = avisos.avisos_curtos()
    assert numero == barbeiro.whatsapp and texto.startswith("Novo horário")


def test_duplo_clique_responde_200_sem_reenviar(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)

    assert _recebi(client, a).status_code == 200
    assert _recebi(client, a).status_code == 200

    assert len(avisos.confirmacoes()) == 1
    avisos.lista.assert_called_once()
    assert _status_cobranca() == ["PAGA"]
    assert _agendamento(a.codigo).status == "CONFIRMADO"


def test_recebi_de_agendamento_cancelado_e_409(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    client.post(
        f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO},
    )
    _sessao(client, barbeiro, b)
    r = _recebi(client, a)
    assert r.status_code == 409 and "cancelado" in r.json()["erro"]
    assert _agendamento(a.codigo).status == "CANCELADO_CLIENTE"
    assert _status_cobranca() == ["CANCELADA"]
    assert avisos.confirmacoes() == []


def test_recebi_de_horario_confirmado_sem_pix_e_409(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, cobra=False)
    a = _agendamento(_marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"])
    _sessao(client, barbeiro, b)
    r = _recebi(client, a)
    assert r.status_code == 409 and "Pix" in r.json()["erro"]


def test_recebi_antes_da_varredura_depois_do_prazo_ainda_confirma(client, cenario, envios, avisos):
    """Passou o prazo mas a varredura ainda nao rodou: o horario segue preso, e
    o dinheiro do cliente vale."""
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _sessao(client, barbeiro, b)
    assert _recebi(client, a).status_code == 200
    assert _agendamento(a.codigo).status == "CONFIRMADO"
    assert _status_cobranca() == ["PAGA"]


# ---- quem pode apertar

def test_o_dono_confirma_o_horario_de_qualquer_barbeiro(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    dono, _ = _barbeiro(b, "Dono")
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, dono, b, papel="DONO")
    assert _recebi(client, a).status_code == 200
    assert _agendamento(a.codigo).status == "CONFIRMADO"


def test_outro_barbeiro_leva_403_e_nada_muda(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    colega, _ = _barbeiro(b, "Colega")
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, colega, b)
    r = _recebi(client, a)
    assert r.status_code == 403 and "erro" in r.json()
    assert _agendamento(a.codigo).status == "AGUARDANDO_PAGAMENTO"
    assert _status_cobranca() == ["ABERTA"]
    assert avisos.confirmacoes() == []


def test_agendamento_de_outra_barbearia_e_404(client, cenario, envios, avisos):
    b, outra = cenario["brutus"], cenario["dontony"]
    barbeiro, servico = _barbeiro(b)
    forasteiro, _ = _barbeiro(outra, "Forasteiro")
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, forasteiro, outra, papel="DONO")
    r = _recebi(client, a, host="dontony.localhost")
    assert r.status_code == 404
    assert _agendamento(a.codigo).status == "AGUARDANDO_PAGAMENTO"


def test_id_inexistente_e_404(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, _ = _barbeiro(b)
    _sessao(client, barbeiro, b)
    r = client.post(
        f"/api/painel/agendamentos/{uuid.uuid4()}/recebi", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404


def test_sem_sessao_e_401(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    assert _recebi(client, a).status_code == 401


# ---- a trava da mensalidade

def test_recebi_passa_pela_trava_da_mensalidade_e_a_vizinha_nao(client, cenario, envios, avisos):
    from tenant.models import Assinatura

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    Assinatura.objects.using("owner").filter(barbearia_id=b.id).update(
        isenta=False, valor_centavos=10000, paga_ate=timezone.localdate() - timedelta(days=7),
    )
    _sessao(client, barbeiro, b)

    with override_settings(**PIX_DO_DONO):
        vizinha = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
        )
        assert vizinha.status_code == 402
        assert _recebi(client, a).status_code == 200
    assert _agendamento(a.codigo).status == "CONFIRMADO"


@pytest.mark.parametrize("caminho,livre", [
    ("/api/painel/agendamentos/abc/recebi", True),
    ("/api/painel/agendamentos/abc/recebi/", False),
    ("/api/painel/agendamentos/abc/def/recebi", False),
    ("/api/painel/agendamentos//recebi", False),
    ("/api/painel/agendamentos/abc/recebidos", False),
    ("/api/painel/agendamentos/abc/cancelar", False),
    ("/api/painel/mensalidade", True),
    ("/api/painel/mensalidade/ja-paguei", True),
])
def test_so_o_recebi_exato_e_livre_no_bloqueio(caminho, livre):
    from tenant.middleware import _livre_no_bloqueio

    assert _livre_no_bloqueio(caminho) is livre


# ---- depois do prazo

def test_recebi_depois_da_varredura_ressuscita_se_a_vaga_segue_livre(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    assert _agendamento(a.codigo).status == "EXPIRADO" and _status_cobranca() == ["EXPIRADA"]

    _sessao(client, barbeiro, b)
    assert _recebi(client, a).status_code == 200

    assert _agendamento(a.codigo).status == "CONFIRMADO"
    [c] = _cobrancas()
    assert (c.status, c.como_foi_paga) == ("PAGA", "MANUAL")
    assert len(avisos.confirmacoes()) == 1


def test_recebi_com_o_horario_ja_comecado_manda_devolver(client, cenario, envios, avisos):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    passado = _agora() - timedelta(minutes=10)
    Agendamento.objects.using("owner").filter(id=a.id).update(
        inicio=passado, fim=passado + timedelta(minutes=30),
    )
    _sessao(client, barbeiro, b)

    r = _recebi(client, a)

    assert r.status_code == 409
    assert "Devolva o Pix de R$ 35,01 pelo app do banco" in r.json()["erro"]
    assert _agendamento(a.codigo).status == "EXPIRADO"
    assert _status_cobranca() == ["EXPIRADA"]
    assert avisos.confirmacoes() == []


def test_recebi_com_a_vaga_tomada_de_verdade_manda_devolver(client, cenario, envios, avisos):
    """O horario expirou e outro cliente o pegou (CONFIRMADO no mesmo
    intervalo): quem manda e' o EXCLUDE do banco."""
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    outro = _chamar_marcar(b, barbeiro, servico, 10 * 60, "PAINEL", whatsapp="11955554444")
    assert outro["status"] == "CONFIRMADO"
    _sessao(client, barbeiro, b)

    r = _recebi(client, a)

    assert r.status_code == 409
    assert r.json()["erro"] == (
        "Esse horário já foi pego por outro cliente. Devolva o Pix de R$ 35,01 pelo app do banco."
    )
    assert _agendamento(a.codigo).status == "EXPIRADO"
    assert _agendamento(outro["codigo"]).status == "CONFIRMADO"
    assert _status_cobranca() == ["EXPIRADA"]
    assert avisos.confirmacoes() == []


def test_deadlock_no_recebi_tambem_e_409(cenario, avisos):
    """40P01 (dois pedidos se esperando na restricao) tem a mesma saida do
    23P01: o horario foi do outro."""
    from app.services.agendamentos import ErroCliente
    from app.services.confirmar_pagamento import confirmar_pagamento

    class Deadlock(Exception):
        sqlstate = "40P01"

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    criado = _chamar_marcar(b, barbeiro, servico, 10 * 60, "SITE")
    erro = OperationalError("deadlock detected")
    erro.__cause__ = Deadlock()
    with patch("app.services.confirmar_pagamento.lembrete_ao_criar", side_effect=erro):
        with pytest.raises(ErroCliente) as e:
            confirmar_pagamento(criado["id"], barbearia_id=b.id, agora=_agora())
    assert e.value.status == 409 and "Devolva o Pix de R$ 35,01" in e.value.mensagem
    assert _agendamento(criado["codigo"]).status == "AGUARDANDO_PAGAMENTO"


def test_outro_erro_de_banco_no_recebi_nao_vira_409(cenario, avisos):
    from app.services.confirmar_pagamento import confirmar_pagamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    criado = _chamar_marcar(b, barbeiro, servico, 10 * 60, "SITE")
    with patch(
        "app.services.confirmar_pagamento.lembrete_ao_criar",
        side_effect=OperationalError("conexao perdida"),
    ):
        with pytest.raises(OperationalError):
            confirmar_pagamento(criado["id"], barbearia_id=b.id, agora=_agora())


# ---- a corrida recebi x varredura (na ordem ruim, de proposito)

def test_corrida_recebi_interrompido_antes_da_cobranca_a_varredura_completa(client, cenario, envios, avisos):
    """O agendamento ja' esta CONFIRMADO e a cobranca ainda ABERTA e vencida
    (o processo parou entre os dois commits): a varredura NAO expira o
    agendamento nem avisa o cliente — ela fecha a cobranca como PAGA."""
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    with patch("app.services.confirmar_pagamento._marcar_cobranca_paga"):
        assert _recebi(client, a).status_code == 200
    _vencer()
    assert _agendamento(a.codigo).status == "CONFIRMADO" and _status_cobranca() == ["ABERTA"]

    contagem = _varrer()

    assert _agendamento(a.codigo).status == "CONFIRMADO"
    assert _status_cobranca() == ["PAGA"]
    assert contagem["pagas"] == 1 and contagem["expirados"] == 0
    assert avisos.expirados() == []


def test_corrida_recebi_interrompido_depois_de_expirada_tambem_fecha_paga(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    _sessao(client, barbeiro, b)
    with patch("app.services.confirmar_pagamento._marcar_cobranca_paga"):
        assert _recebi(client, a).status_code == 200
    assert _status_cobranca() == ["EXPIRADA"]

    _varrer()

    assert _status_cobranca() == ["PAGA"]
    assert _agendamento(a.codigo).status == "CONFIRMADO"


def test_corrida_varredura_expira_o_agendamento_e_o_recebi_chega_antes_da_cobranca(client, cenario, envios, avisos):
    """A varredura ja' expirou o agendamento (commit feito), mas ainda nao
    gravou a cobranca; o "recebi" passa nesse intervalo. Quando a varredura
    grava a dela, o UPDATE condicional nao desfaz o PAGA."""
    from app.services import pix_agendamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _sessao(client, barbeiro, b)

    pendente = {}
    real = pix_agendamento._gravar_cobrancas

    def segurar(novo_estado, agora, contagem):
        pendente.update(novo_estado)  # a varredura "parou" aqui

    with patch.object(pix_agendamento, "_gravar_cobrancas", segurar):
        _varrer()
    assert _agendamento(a.codigo).status == "EXPIRADO" and _status_cobranca() == ["ABERTA"]

    assert _recebi(client, a).status_code == 200
    assert _status_cobranca() == ["PAGA"]

    real(pendente, _agora(), {"expiradas": 0, "pagas": 0, "canceladas": 0})
    assert _status_cobranca() == ["PAGA"]
    assert _agendamento(a.codigo).status == "CONFIRMADO"


def test_corrida_o_recebi_ganha_a_trava_e_a_varredura_encontra_confirmado(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    assert _recebi(client, a).status_code == 200
    _vencer()  # PAGA nao e' ABERTA: nem entra na varredura

    contagem = _varrer()

    assert sum(contagem.values()) == 0
    assert _agendamento(a.codigo).status == "CONFIRMADO" and _status_cobranca() == ["PAGA"]
    assert avisos.expirados() == []


def test_a_coerencia_vale_em_toda_ordem(client, cenario, envios, avisos):
    """Depois de cada combinacao de recebi e varredura (duas rodadas, o recebi
    repetido), o desfecho e' CONFIRMADO com a cobranca PAGA."""
    for ordem in (("v", "r"), ("r", "v"), ("v", "r", "v", "r")):
        from tenant.models import Agendamento, Cobranca

        Cobranca.objects.using("owner").all().delete()
        Agendamento.objects.using("owner").all().delete()
        b = cenario["brutus"]
        barbeiro, servico = _barbeiro(b, f"B{uuid.uuid4().hex[:4]}", chave=f"{uuid.uuid4().hex[:6]}@x.com")
        a = _aguardando(client, b, barbeiro, servico)
        _vencer()
        _sessao(client, barbeiro, b)
        for passo in ordem:
            _varrer() if passo == "v" else _recebi(client, a)
        # A vaga esta livre em todas as ordens: o desfecho e' sempre o mesmo.
        assert _agendamento(a.codigo).status == "CONFIRMADO", ordem
        assert _status_cobranca() == ["PAGA"], ordem


# ---- a varredura

def test_varredura_expira_o_vencido_e_avisa_o_cliente(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()

    contagem = _varrer()

    assert contagem["expirados"] == 1
    assert _agendamento(a.codigo).status == "EXPIRADO"
    assert _status_cobranca() == ["EXPIRADA"]
    [(numero, texto)] = avisos.expirados()
    assert numero == "11977778888"
    assert texto.startswith("*Brutus*\nNão conseguimos confirmar seu Pix a tempo e o horário de ")
    assert "10:00" in texto and "foi liberado" in texto
    assert f"Se você já pagou, fale com Zeca: wa.me/55{barbeiro.whatsapp}" in texto
    assert "não recebemos" not in texto.lower()


def test_varredura_e_idempotente(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    _aguardando(client, b, barbeiro, servico)
    _vencer()

    primeira = _varrer()
    segunda = _varrer()

    assert primeira["expirados"] == 1
    assert sum(segunda.values()) == 0
    assert len(avisos.expirados()) == 1


def test_varredura_deixa_o_que_ainda_esta_no_prazo(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    assert sum(_varrer().values()) == 0
    assert _agendamento(a.codigo).status == "AGUARDANDO_PAGAMENTO" and _status_cobranca() == ["ABERTA"]
    assert avisos.expirados() == []


def test_o_horario_expirado_volta_a_ficar_livre_e_o_centavo_tambem(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    outro = _aguardando(client, b, barbeiro, servico, whatsapp="11966665555")
    assert outro.status == "AGUARDANDO_PAGAMENTO"
    assert [c.valor_centavos for c in _cobrancas()] == [3501, 3501]


def test_varredura_nao_para_nas_barbearias_com_problema(client, cenario, envios, avisos, caplog):
    """A outra barbearia estoura; a do agendamento vencido e' varrida mesmo
    assim, e o defeito fica no log."""
    from app.services import pix_agendamento

    b, defeituosa = cenario["brutus"], cenario["dontony"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    real = pix_agendamento._varrer_barbearia

    def quebra_so_a_defeituosa(bid, *args):
        if str(bid) == str(defeituosa.id):
            raise RuntimeError("barbearia com defeito")
        return real(bid, *args)

    with patch.object(pix_agendamento, "_varrer_barbearia", quebra_so_a_defeituosa):
        contagem = _varrer()

    assert contagem["expirados"] == 1
    assert _agendamento(a.codigo).status == "EXPIRADO"
    assert any("varredura da barbearia" in r.getMessage() for r in caplog.records)


def test_a_orfao_agendamento_sem_cobranca_mais_velho_que_o_prazo_expira(client, cenario, envios, avisos):
    from tenant.models import Agendamento, Cobranca

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    velho = _aguardando(client, b, barbeiro, servico, 10 * 60)
    novo = _aguardando(client, b, barbeiro, servico, 11 * 60, whatsapp="11966665555")
    Cobranca.objects.using("owner").all().delete()
    Agendamento.objects.using("owner").filter(id=velho.id).update(
        criado_em=_agora() - timedelta(minutes=30),
    )

    contagem = _varrer()

    assert contagem["orfaos"] == 1
    assert _agendamento(velho.codigo).status == "EXPIRADO"
    assert _agendamento(novo.codigo).status == "AGUARDANDO_PAGAMENTO"  # ainda dentro do prazo
    [(numero, texto)] = avisos.expirados()
    assert numero == "11977778888" and "foi liberado" in texto
    assert "Não conseguimos gerar o Pix" in texto and "confirmar seu Pix" not in texto
    assert sum(_varrer().values()) == 0  # e nao avisa de novo


def test_a_orfao_com_cobranca_cancelada_tambem_expira(client, cenario, envios, avisos):
    from tenant.models import Agendamento, Cobranca

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    Cobranca.objects.using("owner").all().update(status="CANCELADA")
    Agendamento.objects.using("owner").filter(id=a.id).update(
        criado_em=_agora() - timedelta(minutes=30),
    )
    assert _varrer()["orfaos"] == 1
    assert _agendamento(a.codigo).status == "EXPIRADO"


def test_b_cobranca_aberta_de_agendamento_cancelado_e_cancelada(client, cenario, envios, avisos):
    """O cancelamento comitou, mas a escrita da cobranca falhou: o centavo
    ficaria preso. A varredura solta, sem avisar ninguem."""
    from tenant.models import Agendamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    Agendamento.objects.using("owner").filter(id=a.id).update(status="CANCELADO_CLIENTE")
    assert _status_cobranca() == ["ABERTA"]  # ainda dentro do prazo e mesmo assim

    contagem = _varrer()

    assert _status_cobranca() == ["CANCELADA"]
    assert contagem["canceladas"] == 1 and contagem["expirados"] == 0
    assert avisos.expirados() == []
    assert sum(_varrer().values()) == 0


def test_b_cobranca_aberta_de_agendamento_expirado_e_expirada_sem_avisar(client, cenario, envios, avisos):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    Agendamento.objects.using("owner").filter(id=a.id).update(status="EXPIRADO")
    _varrer()
    assert _status_cobranca() == ["EXPIRADA"]
    assert avisos.expirados() == []


def test_falha_ao_voltar_para_confirmado_deixa_aguardando_que_a_varredura_limpa(cenario, avisos):
    """O caso da revisao da P3: a cobranca nao abriu E o proprio retorno para
    CONFIRMADO falhou. O agendamento fica AGUARDANDO sem cobranca ate a
    varredura (a) liberar o horario."""
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    with patch(
        "app.services.agendamentos.pix_agendamento.abrir", side_effect=RuntimeError("banco caiu"),
    ), patch("app.services.agendamentos.lembrete_ao_criar", side_effect=RuntimeError("caiu de novo")):
        with pytest.raises(RuntimeError):
            _chamar_marcar(b, barbeiro, servico, 10 * 60, "SITE")
    from tenant.models import Agendamento

    [preso] = Agendamento.objects.using("owner").all()
    assert preso.status == "AGUARDANDO_PAGAMENTO" and _cobrancas() == []
    Agendamento.objects.using("owner").filter(id=preso.id).update(
        criado_em=_agora() - timedelta(minutes=30),
    )

    assert _varrer()["orfaos"] == 1

    assert _agendamento(preso.codigo).status == "EXPIRADO"
    # E o horario voltou a ser marcavel.
    outro = _chamar_marcar(b, barbeiro, servico, 10 * 60, "PAINEL", whatsapp="11955554444")
    assert outro["status"] == "CONFIRMADO"


# ---- marcar() expira o vencido do barbeiro antes da vaga

def test_marcar_libera_o_horario_vencido_sem_esperar_o_beat(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    antigo = _aguardando(client, b, barbeiro, servico)
    _vencer()

    r = _marcar_no_site(client, barbeiro, servico, 10 * 60, whatsapp="11966665555")

    assert r.status_code == 201
    assert _agendamento(antigo.codigo).status == "EXPIRADO"
    assert _agendamento(r.json()["codigo"]).status == "AGUARDANDO_PAGAMENTO"
    [(numero, texto)] = avisos.expirados()
    assert numero == "11977778888" and "foi liberado" in texto
    # A varredura que vem depois nao avisa de novo.
    _varrer()
    assert len(avisos.expirados()) == 1


def test_marcar_so_expira_os_do_barbeiro_do_pedido(client, cenario, envios, avisos):
    b = cenario["brutus"]
    ana, servico = _barbeiro(b, "Ana")
    beto, _ = _barbeiro(b, "Beto", chave="beto@x.com")
    da_ana = _aguardando(client, b, ana, servico)
    _vencer()

    _marcar_no_site(client, beto, servico, 11 * 60, whatsapp="11966665555")

    assert _agendamento(da_ana.codigo).status == "AGUARDANDO_PAGAMENTO"
    assert avisos.expirados() == []


def test_marcar_segue_mesmo_se_a_expiracao_falhar(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    _aguardando(client, b, barbeiro, servico)
    _vencer()
    with patch(
        "app.services.agendamentos.pix_agendamento.expirar_vencidos", side_effect=RuntimeError("x"),
    ):
        r = _marcar_no_site(client, barbeiro, servico, 11 * 60, whatsapp="11966665555")
    assert r.status_code == 201


def test_marcar_nao_abre_transacao_do_tenant_sem_vencido(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    with patch("app.services.agendamentos.pix_agendamento.expirar_vencidos") as varre:
        _marcar_no_site(client, barbeiro, servico, 10 * 60)
    varre.assert_not_called()


# ---- o beat

def test_o_beat_roda_a_varredura_a_cada_minuto():
    from django.conf import settings

    agenda = settings.CELERY_BEAT_SCHEDULE["expirar-pix-vencidos"]
    assert agenda["task"] == "app.tasks.expirar_pix_vencidos"
    assert agenda["schedule"] == 60.0


def test_a_tarefa_chama_a_varredura(cenario, avisos):
    from app import tasks

    with patch("app.tasks.expirar_vencidos", return_value={"expirados": 0}) as varre:
        assert tasks.expirar_pix_vencidos() == {"expirados": 0}
    varre.assert_called_once()


# ---- cancelar o que ja' estava pago

def _pago(client, b, barbeiro, servico, minutos=10 * 60, whatsapp="11977778888"):
    """Um horario CONFIRMADO com Pix pago, pelo caminho de verdade."""
    from app.services.confirmar_pagamento import confirmar_pagamento

    a = _aguardando(client, b, barbeiro, servico, minutos, whatsapp)
    confirmar_pagamento(a.id, barbearia_id=b.id, agora=_agora())
    assert _agendamento(a.codigo).status == "CONFIRMADO"
    return a


def test_cliente_cancela_o_pago_e_o_barbeiro_recebe_o_aviso_de_devolver(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _pago(client, b, barbeiro, servico)
    avisos.lista.reset_mock()  # (o mesmo avisar_mudanca que `envios` simula)

    r = client.post(f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO})

    assert r.status_code == 200
    [(numero, texto)] = avisos.devolucoes()
    assert numero == barbeiro.whatsapp
    assert texto.startswith("José Neto cancelou ")
    assert "Esse horário estava pago (R$ 35,01) — devolva o Pix pelo app do banco." in texto
    # Os avisos de hoje continuam: a lista do dia e' refeita como sempre.
    avisos.lista.assert_called_once()
    assert str(avisos.lista.call_args.kwargs["cancelados"][0][0]) == str(a.id)


def test_painel_cancela_o_pago_e_a_resposta_traz_o_valor(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _pago(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)

    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
        )

    assert r.status_code == 200 and r.json() == {"ok": True, "pagoCentavos": 3501}
    [(numero, texto)] = avisos.devolucoes()
    assert numero == barbeiro.whatsapp
    assert "Esse horário estava pago (R$ 35,01)" in texto and "devolva o Pix" in texto
    assert "José Neto" in texto


def test_painel_cancela_o_nao_pago_sem_valor_e_sem_aviso(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, cobra=False)
    a = _agendamento(_marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"])
    _sessao(client, barbeiro, b)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.json() == {"ok": True, "pagoCentavos": None}
    assert avisos.devolucoes() == []


def test_bloquear_o_cliente_avisa_a_devolucao_dos_pagos(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    pago = _pago(client, b, barbeiro, servico, 10 * 60)
    _aguardando(client, b, barbeiro, servico, 11 * 60)  # esperando Pix: nada a devolver
    _sessao(client, barbeiro, b)

    r = client.post(
        f"/api/painel/agendamentos/{pago.id}/bloquear-cliente", headers={"host": HOST, **CABECALHO},
    )

    assert r.status_code == 200
    [(numero, texto)] = avisos.devolucoes()
    assert numero == barbeiro.whatsapp and "R$ 35,01" in texto and "devolva o Pix" in texto


def test_cancelar_horario_confirmado_sem_pix_nao_manda_devolver(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, cobra=False)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    client.post(f"/api/agendamentos/{codigo}/cancelar", headers={"host": HOST, **CABECALHO})
    assert avisos.devolucoes() == []


def test_cancelar_aguardando_continua_sem_aviso_de_devolucao(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    client.post(f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO})
    assert avisos.devolucoes() == []


# ---- o recebi 409 de cancelado manda devolver

def test_recebi_de_cancelado_com_cobranca_manda_devolver(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    client.post(f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO})
    _sessao(client, barbeiro, b)
    r = _recebi(client, a)
    assert r.status_code == 409
    assert r.json()["erro"] == (
        "Esse horário foi cancelado. Se o Pix caiu, devolva o Pix de R$ 35,01 pelo app do banco."
    )


# ---- recebi x cancelamento (a sonda da revisao)

def _confirmado_com_cobranca_atrasada(client, b, barbeiro, servico, minutos=10 * 60):
    """O "recebi" ja' comitou o agendamento, mas a escrita da cobranca (outra
    conexao) ainda nao chegou: CONFIRMADO com cobranca ABERTA."""
    from app.services.confirmar_pagamento import confirmar_pagamento

    a = _aguardando(client, b, barbeiro, servico, minutos)
    with patch("app.services.confirmar_pagamento._marcar_cobranca_paga"):
        confirmar_pagamento(a.id, barbearia_id=b.id, agora=_agora())
    assert _agendamento(a.codigo).status == "CONFIRMADO" and _status_cobranca()[-1] == "ABERTA"
    return a


def _recebi_numa_thread_enquanto_cancela(b, a, *, onde):
    """Roda `onde` (um servico de cancelamento) e, dentro dele, DEPOIS de ele
    ter trancado a linha, dispara o "recebi" numa thread: a thread tem de ficar
    esperando a trava (viva depois de 1,5 s), nunca passar no meio."""
    import threading

    from django.db import connections

    from app.services import pix_agendamento
    from app.services.agendamentos import ErroCliente
    from app.services.confirmar_pagamento import confirmar_pagamento

    resultado = {}

    def recebi():
        try:
            confirmar_pagamento(a.id, barbearia_id=b.id, agora=_agora())
            resultado["erro"] = None
        except ErroCliente as e:
            resultado["erro"] = e
        finally:
            connections.close_all()

    thread = threading.Thread(target=recebi)
    real = pix_agendamento.valor_pago
    feito = []

    def valor_pago_com_recebi_no_meio(*args):
        if not feito:
            feito.append(1)
            thread.start()
            thread.join(1.5)
            resultado["bloqueada"] = thread.is_alive()
        return real(*args)

    with patch.object(pix_agendamento, "valor_pago", valor_pago_com_recebi_no_meio):
        saida = onde()
    thread.join(10)
    assert not thread.is_alive()
    return saida, resultado


def _confere_que_o_cancelamento_ganhou(a, resultado, avisos):
    assert resultado["bloqueada"] is True  # esperou a trava, nao passou no meio
    assert resultado["erro"].status == 409
    assert "devolva o Pix de R$ 35,01" in resultado["erro"].mensagem
    assert _agendamento(a.codigo).status.startswith("CANCELADO")
    assert _status_cobranca() == ["CANCELADA"]
    assert avisos.confirmacoes() == []
    assert avisos.devolucoes() == []


def test_cancelar_publico_x_recebi_no_meio_o_cancelamento_ganha(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    r, resultado = _recebi_numa_thread_enquanto_cancela(
        b, a, onde=lambda: client.post(
            f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO},
        ),
    )
    assert r.status_code == 200
    _confere_que_o_cancelamento_ganhou(a, resultado, avisos)
    assert _agendamento(a.codigo).status == "CANCELADO_CLIENTE"


def test_cancelar_do_painel_x_recebi_no_meio_o_cancelamento_ganha(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r, resultado = _recebi_numa_thread_enquanto_cancela(
            b, a, onde=lambda: client.post(
                f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
            ),
        )
    assert r.status_code == 200 and r.json() == {"ok": True, "pagoCentavos": None}
    _confere_que_o_cancelamento_ganhou(a, resultado, avisos)


def test_bloquear_x_recebi_no_meio_o_bloqueio_ganha(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    r, resultado = _recebi_numa_thread_enquanto_cancela(
        b, a, onde=lambda: client.post(
            f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers={"host": HOST, **CABECALHO},
        ),
    )
    assert r.status_code == 200
    _confere_que_o_cancelamento_ganhou(a, resultado, avisos)


def _confere_pago_e_cancelado(a, avisos):
    assert _agendamento(a.codigo).status.startswith("CANCELADO")
    assert _status_cobranca() == ["PAGA"]  # o dinheiro entrou: nunca CANCELADA
    [(numero, texto)] = avisos.devolucoes()
    assert "R$ 35,01" in texto and "devolva o Pix" in texto


def test_cancelar_publico_apos_recebi_com_cobranca_atrasada_manda_devolver(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _confirmado_com_cobranca_atrasada(client, b, barbeiro, servico)
    avisos.lista.reset_mock()
    r = client.post(f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO})
    assert r.status_code == 200
    _confere_pago_e_cancelado(a, avisos)
    avisos.lista.assert_called_once()  # a lista do dia tambem sai, como em todo confirmado
    assert sum(_varrer().values()) == 0  # e nada a reparar depois


def test_cancelar_do_painel_apos_recebi_com_cobranca_atrasada_traz_o_valor(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _confirmado_com_cobranca_atrasada(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.json() == {"ok": True, "pagoCentavos": 3501}
    _confere_pago_e_cancelado(a, avisos)


def test_bloquear_apos_recebi_com_cobranca_atrasada_manda_devolver(client, cenario, envios, avisos):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _confirmado_com_cobranca_atrasada(client, b, barbeiro, servico)
    _sessao(client, barbeiro, b)
    r = client.post(
        f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    _confere_pago_e_cancelado(a, avisos)


# ---- o reparo se guia pelo agendamento, de qualquer idade

def test_reparo_de_confirmado_com_cobranca_expirada_ha_dias(client, cenario, envios, avisos):
    from tenant.models import Cobranca

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    a = _aguardando(client, b, barbeiro, servico)
    _vencer()
    _varrer()
    _sessao(client, barbeiro, b)
    with patch("app.services.confirmar_pagamento._marcar_cobranca_paga"):
        assert _recebi(client, a).status_code == 200
    Cobranca.objects.using("owner").update(expira_em=_agora() - timedelta(days=5))
    assert _status_cobranca() == ["EXPIRADA"]

    _varrer()

    assert _status_cobranca() == ["PAGA"]


# ---- uma rodada de cada vez

def test_rodada_anterior_ainda_rodando_pula_a_tarefa(cenario):
    from django.db import connections

    from app import tasks
    from app.services.pix_agendamento import TRAVA_DA_VARREDURA

    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", [TRAVA_DA_VARREDURA])
        try:
            with patch("app.tasks.expirar_vencidos") as varre:
                assert tasks.expirar_pix_vencidos() == {"pulada": True}
            varre.assert_not_called()
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", [TRAVA_DA_VARREDURA])
    with patch("app.tasks.expirar_vencidos", return_value={"expirados": 0}) as varre:
        assert tasks.expirar_pix_vencidos() == {"expirados": 0}
    varre.assert_called_once()
    # E a trava foi devolvida: a proxima rodada passa de novo.
    with patch("app.tasks.expirar_vencidos", return_value={}):
        assert tasks.expirar_pix_vencidos() == {}
