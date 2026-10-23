import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

BRASILIA = ZoneInfo("America/Sao_Paulo")
PIX = {
    "PIX_CHAVE": "Dono@Marcai.com",
    "PIX_NOME_RECEBEDOR": "Marcai",
    "PIX_CIDADE": "Patos",
}


def momento(ano, mes, dia, hora=12, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=BRASILIA)


@pytest.fixture(autouse=True)
def _pix():
    with override_settings(**PIX):
        yield


def _paga(barbearia_id, *, valor=10000, paga_ate=date(2026, 10, 10), dia=10, **extra):
    from tenant.models import Assinatura

    Assinatura.objects.using("admin").filter(barbearia_id=barbearia_id).update(
        isenta=False, valor_centavos=valor, paga_ate=paga_ate,
        dia_de_vencimento=dia, **extra,
    )


@pytest.fixture
def b(cenario):
    _paga(cenario["brutus"].id)
    return cenario["brutus"].id


@pytest.fixture
def barbeiro(b):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").get(barbearia_id=b).id


def _assinatura(b):
    from tenant.models import Assinatura

    return Assinatura.objects.using("admin").get(barbearia_id=b)


def _recarregar(c):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").get(id=c.id)


# --- leitura ---

def test_barbearia_sem_assinatura_vale_como_isenta(b):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao
    from tenant.models import Assinatura

    Assinatura.objects.using("admin").filter(barbearia_id=b).delete()
    assert operacoes.leitura(b, agora=momento(2026, 12, 1)).situacao == Situacao.ISENTA


def test_23h30_de_brasilia_no_vencimento_ainda_e_o_dia(b):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao
    from datetime import timezone as fuso

    agora = datetime(2026, 10, 11, 2, 30, tzinfo=fuso.utc)
    leitura = operacoes.leitura(b, agora=agora)
    assert (leitura.situacao, leitura.dias) == (Situacao.VENCENDO, 0)


def test_bloqueada_seis_dias_depois(b):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    assert operacoes.leitura(b, agora=momento(2026, 10, 16)).situacao == Situacao.BLOQUEADA


def test_barbearia_desativada_le_desativada(b):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao
    from tenant.models import Barbearia

    Barbearia.objects.using("admin").filter(id=b).update(ativo=False)
    assert operacoes.leitura(b, agora=momento(2026, 10, 12)).situacao == Situacao.DESATIVADA


def test_leitura_nao_cria_cobranca(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    operacoes.leitura(b, agora=momento(2026, 10, 12))
    assert not Cobranca.objects.using("admin").exists()


# --- cobranca_do_ciclo ---

def test_em_dia_nao_abre_cobranca(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    # paga ate 10/10, hoje 01/10: faltam 9 dias, fora da janela de 5
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 1)) is None
    assert not Cobranca.objects.using("admin").filter(barbearia_id=b).exists()


def test_vencendo_abre_cobranca(b):
    from app.services.mensalidade import operacoes

    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 7)) is not None


def test_em_dia_com_cobranca_aberta_devolve_none_e_deixa_a_linha(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 7))
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 1)) is None
    assert Cobranca.objects.using("admin").filter(barbearia_id=b, status="ABERTA").count() == 1


def test_cobranca_nasce_com_centavo_chave_normalizada_e_copia_e_cola(b):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert c.status == "ABERTA" and c.motivo == "MENSALIDADE"
    assert c.chave_pix == "dono@marcai.com"
    assert (c.valor_base_centavos, c.valor_centavos) == (10000, 10001)
    # o valor com os centavos vai dentro do copia e cola (campo 54)
    assert "5406100.01" in c.copia_e_cola
    assert "dono@marcai.com" in c.copia_e_cola


def test_cobranca_do_ciclo_devolve_a_mesma_aberta(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    a = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    de_novo = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 13))
    assert a.id == de_novo.id
    assert Cobranca.objects.using("admin").count() == 1


def test_duas_barbearias_com_o_mesmo_valor_levam_centavos_diferentes(cenario):
    from app.services.mensalidade import operacoes

    a, o = cenario["brutus"].id, cenario["dontony"].id
    _paga(a)
    _paga(o)
    ca = operacoes.cobranca_do_ciclo(a, agora=momento(2026, 10, 12))
    co = operacoes.cobranca_do_ciclo(o, agora=momento(2026, 10, 12))
    assert (ca.valor_centavos, co.valor_centavos) == (10001, 10002)


def test_centavo_de_cobranca_paga_volta_a_ficar_livre(cenario):
    from app.services.mensalidade import operacoes

    a, o = cenario["brutus"].id, cenario["dontony"].id
    _paga(a)
    _paga(o)
    ca = operacoes.cobranca_do_ciclo(a, agora=momento(2026, 10, 12))
    operacoes.confirmar(ca.id, agora=momento(2026, 10, 12, 13))
    co = operacoes.cobranca_do_ciclo(o, agora=momento(2026, 10, 12, 14))
    assert co.valor_centavos == 10001


@pytest.mark.parametrize("mudanca", [
    {"isenta": True},
    {"valor_centavos": 0},
])
def test_sem_cobranca_para_isenta_ou_valor_zero(b, mudanca):
    from app.services.mensalidade import operacoes
    from tenant.models import Assinatura

    Assinatura.objects.using("admin").filter(barbearia_id=b).update(**mudanca)
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12)) is None


def test_sem_cobranca_sem_chave_pix_ou_sem_assinatura_ou_desativada(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Assinatura, Barbearia

    with override_settings(PIX_CHAVE=""):
        assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12)) is None
    Barbearia.objects.using("admin").filter(id=b).update(ativo=False)
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12)) is None
    Barbearia.objects.using("admin").filter(id=b).update(ativo=True)
    Assinatura.objects.using("admin").filter(barbearia_id=b).delete()
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12)) is None


def test_sem_centavo_livre_recusa_com_frase_para_a_tela(b):
    from app.services.mensalidade import operacoes

    ocupados = [10000 + k for k in range(1, 100)]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(operacoes, "_ocupados", lambda chave: set(ocupados))
        with pytest.raises(operacoes.RecusaDaMensalidade) as r:
            operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert "Pix" in r.value.mensagem


def test_corrida_pelo_mesmo_centavo_tenta_de_novo(cenario):
    """Outra barbearia pega o centavo entre a escolha e o INSERT: o indice
    unico recusa, e a escolha e refeita em vez de estourar."""
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    a, o = cenario["brutus"].id, cenario["dontony"].id
    _paga(a)
    _paga(o)
    real = operacoes._ocupados
    chamadas = []

    def cega_na_primeira(chave):
        chamadas.append(1)
        if len(chamadas) == 1:
            # A concorrente grava 10001 logo depois da nossa leitura.
            Cobranca.objects.using("admin").create(
                barbearia_id=o, motivo="MENSALIDADE", chave_pix="dono@marcai.com",
                valor_base_centavos=10000, valor_centavos=10001, copia_e_cola="x",
            )
            return set()
        return real(chave)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(operacoes, "_ocupados", cega_na_primeira)
        c = operacoes.cobranca_do_ciclo(a, agora=momento(2026, 10, 12))
    assert c.valor_centavos == 10002
    assert len(chamadas) == 2


# --- informar_pagamento ---

def test_ja_paguei_marca_a_cobranca_e_segura_o_painel(b, barbeiro):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    agora = momento(2026, 10, 20)
    c = operacoes.informar_pagamento(b, barbeiro, agora=agora)
    assert c.informada_em == agora and c.informada_por_id == barbeiro
    assert c.status == "ABERTA"
    assert operacoes.leitura(b, agora=agora).situacao == Situacao.AGUARDANDO


def test_segundo_ja_paguei_e_recusado_e_fica_um_aviso_so(b, barbeiro):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    primeiro = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    with pytest.raises(operacoes.RecusaDaMensalidade) as r:
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12, 12, 1))
    assert "aguardando confirmação" in r.value.mensagem
    assert Cobranca.objects.using("admin").count() == 1
    assert _recarregar(primeiro).informada_em == momento(2026, 10, 12)


def test_passada_a_espera_de_tres_dias_pode_avisar_de_novo(b, barbeiro):
    from app.services.mensalidade import operacoes

    operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 16))
    assert c.informada_em == momento(2026, 10, 16)


def test_desativada_isenta_ou_sem_chave_nao_informa(b, barbeiro):
    from app.services.mensalidade import operacoes
    from tenant.models import Assinatura, Barbearia

    with override_settings(PIX_CHAVE=""):
        with pytest.raises(operacoes.RecusaDaMensalidade):
            operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    Assinatura.objects.using("admin").filter(barbearia_id=b).update(isenta=True)
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    Barbearia.objects.using("admin").filter(id=b).update(ativo=False)
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))


# --- confirmar / recusar ---

def test_confirmar_na_carencia_mantem_o_dia(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    c = operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 15))
    assert _assinatura(b).paga_ate == date(2026, 11, 10)
    c = _recarregar(c)
    assert c.status == "PAGA" and c.como_foi_paga == "MANUAL"
    assert c.paga_em == momento(2026, 10, 12, 15)
    assert c.paga_ate_depois == date(2026, 11, 10)


def test_confirmar_bloqueada_recomeca_de_hoje(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 20))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 20, 15))
    a = _assinatura(b)
    assert (a.paga_ate, a.dia_de_vencimento) == (date(2026, 11, 20), 20)


def test_confirmar_pelo_vigia_grava_como_foi_paga(b):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 13), como="VIGIA")
    assert _recarregar(c).como_foi_paga == "VIGIA"


def test_confirmar_duas_vezes_avanca_uma_so(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 15))
    with pytest.raises(operacoes.RecusaDaMensalidade) as r:
        operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 15, 1))
    assert "já foi resolvido" in r.value.mensagem
    assert _assinatura(b).paga_ate == date(2026, 11, 10)


def test_recusar_limpa_o_aviso_e_deixa_aberta_sem_mexer_no_paga_ate(b, barbeiro):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 20))
    operacoes.recusar(c.id, agora=momento(2026, 10, 20, 15))
    c = _recarregar(c)
    assert c.status == "ABERTA"
    assert c.informada_em is None and c.informada_por_id is None
    assert c.recusada_em == momento(2026, 10, 20, 15)
    assert _assinatura(b).paga_ate == date(2026, 10, 10)
    assert operacoes.leitura(b, agora=momento(2026, 10, 20, 16)).situacao == Situacao.BLOQUEADA


def test_recusar_sem_aviso_ou_ja_paga_e_recusado(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.recusar(c.id, agora=momento(2026, 10, 12, 13))
    operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12, 14))
    operacoes.confirmar(c.id, agora=momento(2026, 10, 12, 15))
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.recusar(c.id, agora=momento(2026, 10, 12, 16))


def test_confirmar_cobranca_que_nao_e_mensalidade_e_recusado(b):
    from app.services.mensalidade import operacoes
    from tenant.models import Cobranca

    c = Cobranca.objects.using("admin").create(
        barbearia_id=b, motivo="AGENDAMENTO", chave_pix="x@y.com",
        valor_base_centavos=1000, valor_centavos=1001, copia_e_cola="x",
    )
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.confirmar(c.id, agora=momento(2026, 10, 12))


# --- registrar_manual ---

def test_registrar_manual_cria_paga_e_cancela_a_aberta(b):
    from app.services.mensalidade import operacoes

    aberta = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    c = operacoes.registrar_manual(
        b, paga_ate=date(2026, 12, 5), valor_centavos=10000,
        observacao="pagou em dinheiro", agora=momento(2026, 10, 12),
    )
    assert (c.status, c.como_foi_paga) == ("PAGA", "REGISTRO")
    assert c.paga_ate_depois == date(2026, 12, 5) and c.observacao == "pagou em dinheiro"
    assert (c.valor_base_centavos, c.valor_centavos) == (10000, 10000)
    assert c.copia_e_cola == "" and c.chave_pix == "dono@marcai.com"
    assert _recarregar(aberta).status == "CANCELADA"
    a = _assinatura(b)
    assert (a.paga_ate, a.dia_de_vencimento) == (date(2026, 12, 5), 5)


def test_registrar_manual_sem_aberta_nem_chave(b):
    from app.services.mensalidade import operacoes

    with override_settings(PIX_CHAVE=""):
        c = operacoes.registrar_manual(
            b, paga_ate=date(2026, 12, 5), valor_centavos=9000, agora=momento(2026, 10, 12),
        )
    assert c.chave_pix == "" and c.status == "PAGA"


# --- ja paguei depois de recusado; o que nao e' cobravel ---

def test_ja_paguei_recusado_nao_pode_ser_repetido_na_mesma_cobranca(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    operacoes.recusar(c.id, agora=momento(2026, 10, 12, 15))
    with pytest.raises(operacoes.RecusaDaMensalidade) as r:
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12, 16))
    assert r.value.mensagem == "O pagamento informado foi recusado. Fale com o Marcaí."
    # Nem dias depois: a recusa e' uma resposta, nao uma espera.
    with pytest.raises(operacoes.RecusaDaMensalidade):
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 20))
    assert _recarregar(c).informada_em is None


def test_ja_paguei_sem_resposta_em_tres_dias_pode_avisar_de_novo(b, barbeiro):
    from app.services.mensalidade import operacoes

    c = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    de_novo = operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 15, 12, 1))
    assert de_novo.id == c.id and de_novo.informada_em == momento(2026, 10, 15, 12, 1)


@pytest.mark.parametrize("config", [
    {"PIX_CHAVE": ""}, {"PIX_NOME_RECEBEDOR": ""}, {"PIX_CIDADE": ""},
])
def test_sem_pix_completo_le_como_isenta(b, config):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    with override_settings(**config):
        assert operacoes.leitura(b, agora=momento(2026, 10, 20)).situacao == Situacao.ISENTA
        assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 20)) is None


def test_valor_zero_le_como_isenta(b):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    _paga(b, valor=0)
    assert operacoes.leitura(b, agora=momento(2026, 10, 20)).situacao == Situacao.ISENTA


# --- InfinitePay ---
IP = {"INFINITEPAY_HANDLE": "marcai", "INFINITEPAY_WEBHOOK_SEGREDO": "s3gredo"}
LINK = "https://checkout.infinitepay.io/x/abc"


@pytest.fixture
def ip(monkeypatch):
    """Liga a InfinitePay com o `criar_link` trocado. `ip.chamadas` guarda o
    que foi pedido; `ip.erro` faz o falso levantar."""
    from app.services import infinitepay

    class Falso:
        chamadas = []
        erro = None

        def __call__(self, **kw):
            self.chamadas.append(kw)
            if self.erro:
                raise self.erro
            return LINK

    falso = Falso()
    falso.chamadas = []
    monkeypatch.setattr(infinitepay, "criar_link", falso)
    with override_settings(**IP):
        yield falso


def test_com_infinitepay_a_cobranca_sai_com_valor_redondo(b, ip):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert (c.valor_base_centavos, c.valor_centavos) == (10000, 10000)
    assert c.chave_pix == f"ip:{c.id}"
    assert c.link_pagamento == LINK
    assert c.copia_e_cola == ""
    (chamada,) = ip.chamadas
    assert chamada["referencia"] == str(c.id)
    assert chamada["valor_centavos"] == 10000
    assert chamada["barbearia_slug"] == "brutus"
    assert operacoes.eh_da_infinitepay(c) is True


def test_duas_barbearias_mesmo_preco_nao_disputam_centavo(cenario, ip):
    from app.services.mensalidade import operacoes

    a, o = cenario["brutus"].id, cenario["dontony"].id
    _paga(a)
    _paga(o)
    ca = operacoes.cobranca_do_ciclo(a, agora=momento(2026, 10, 12))
    co = operacoes.cobranca_do_ciclo(o, agora=momento(2026, 10, 12))
    assert ca.valor_centavos == co.valor_centavos == 10000


def test_sem_infinitepay_continua_o_pix_com_centavo(b):
    from app.services.mensalidade import operacoes

    c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert c.valor_centavos == 10001
    assert c.link_pagamento == ""
    assert operacoes.eh_da_infinitepay(c) is False


def test_com_infinitepay_cobra_mesmo_sem_o_pix_estatico(b, ip):
    from app.services.mensalidade import operacoes

    with override_settings(PIX_CHAVE="", PIX_NOME_RECEBEDOR="", PIX_CIDADE=""):
        c = operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert c is not None and c.link_pagamento == LINK


def test_isenta_nao_gera_link(b, ip):
    from app.services.mensalidade import operacoes
    from tenant.models import Assinatura

    Assinatura.objects.using("admin").filter(barbearia_id=b).update(isenta=True)
    assert operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12)) is None
    assert ip.chamadas == []


def test_nunca_bloquear_continua_sem_bloquear_com_infinitepay(b, ip):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.situacao import Situacao

    _paga(b, nunca_bloquear=True)
    lido = operacoes.leitura(b, agora=momento(2026, 10, 30))
    assert lido.situacao != Situacao.BLOQUEADA


def test_infinitepay_fora_do_ar_nao_grava_cobranca(b, ip):
    from app.services.infinitepay import ErroDaInfinitePay
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.operacoes import RecusaDaMensalidade
    from tenant.models import Cobranca

    ip.erro = ErroDaInfinitePay("fora")
    with pytest.raises(RecusaDaMensalidade) as e:
        operacoes.cobranca_do_ciclo(b, agora=momento(2026, 10, 12))
    assert e.value.mensagem == (
        "Não foi possível gerar o link de pagamento agora. Tente de novo em alguns minutos."
    )
    assert not Cobranca.objects.using("admin").filter(barbearia_id=b).exists()


def test_ja_paguei_recusado_quando_e_automatico(b, barbeiro, ip):
    from app.services.mensalidade import operacoes
    from app.services.mensalidade.operacoes import RecusaDaMensalidade

    with pytest.raises(RecusaDaMensalidade) as e:
        operacoes.informar_pagamento(b, barbeiro, agora=momento(2026, 10, 12))
    assert e.value.mensagem == "A confirmação deste pagamento é automática."
