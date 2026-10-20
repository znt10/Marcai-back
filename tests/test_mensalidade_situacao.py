from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.mensalidade.situacao import (
    TRAVAM_O_PAINEL,
    Situacao,
    hoje_em_sao_paulo,
    ler_situacao,
    novo_paga_ate,
)

BRASILIA = ZoneInfo("America/Sao_Paulo")
PAGA_ATE = date(2026, 10, 10)


def ler(hoje, **mudanca):
    campos = {
        "barbearia_ativa": True,
        "isenta": False,
        "nunca_bloquear": False,
        "paga_ate": PAGA_ATE,
        "aviso_em": None,
        "hoje": hoje,
        "agora": datetime(hoje.year, hoje.month, hoje.day, 12, 0, tzinfo=BRASILIA),
    }
    campos.update(mudanca)
    return ler_situacao(**campos)


# --- fronteiras de data ---

def test_seis_dias_antes_esta_em_dia():
    assert ler(PAGA_ATE - timedelta(days=6)).situacao == Situacao.EM_DIA


def test_cinco_dias_antes_ja_esta_vencendo():
    leitura = ler(PAGA_ATE - timedelta(days=5))
    assert (leitura.situacao, leitura.dias) == (Situacao.VENCENDO, 5)


def test_no_dia_do_vencimento_ainda_esta_vencendo():
    leitura = ler(PAGA_ATE)
    assert (leitura.situacao, leitura.dias) == (Situacao.VENCENDO, 0)


def test_um_dia_depois_esta_atrasada():
    leitura = ler(PAGA_ATE + timedelta(days=1))
    assert (leitura.situacao, leitura.dias) == (Situacao.ATRASADA, 1)


def test_cinco_dias_depois_ainda_e_carencia():
    assert ler(PAGA_ATE + timedelta(days=5)).situacao == Situacao.ATRASADA


def test_seis_dias_depois_bloqueia():
    leitura = ler(PAGA_ATE + timedelta(days=6))
    assert (leitura.situacao, leitura.dias) == (Situacao.BLOQUEADA, 6)
    assert leitura.situacao in TRAVAM_O_PAINEL


def test_bloqueia_em_e_o_primeiro_dia_bloqueado():
    assert ler(PAGA_ATE).bloqueia_em == date(2026, 10, 16)


# --- excecoes ---

def test_nunca_bloquear_fica_atrasada_para_sempre():
    leitura = ler(PAGA_ATE + timedelta(days=60), nunca_bloquear=True)
    assert (leitura.situacao, leitura.dias) == (Situacao.ATRASADA, 60)
    assert leitura.bloqueia_em is None


def test_isenta_sempre():
    assert ler(PAGA_ATE + timedelta(days=90), isenta=True).situacao == Situacao.ISENTA


def test_desativada_ganha_de_tudo():
    leitura = ler(PAGA_ATE, barbearia_ativa=False, isenta=True)
    assert leitura.situacao == Situacao.DESATIVADA
    assert leitura.situacao in TRAVAM_O_PAINEL


def test_aviso_de_dois_dias_segura_o_bloqueio():
    hoje = PAGA_ATE + timedelta(days=10)
    agora = datetime(hoje.year, hoje.month, hoje.day, 12, 0, tzinfo=BRASILIA)
    leitura = ler(hoje, agora=agora, aviso_em=agora - timedelta(days=2))
    assert leitura.situacao == Situacao.AGUARDANDO


def test_aviso_de_quatro_dias_nao_segura_mais():
    hoje = PAGA_ATE + timedelta(days=10)
    agora = datetime(hoje.year, hoje.month, hoje.day, 12, 0, tzinfo=BRASILIA)
    leitura = ler(hoje, agora=agora, aviso_em=agora - timedelta(days=4))
    assert leitura.situacao == Situacao.BLOQUEADA


# --- fuso: entre 00:00 e 03:00 UTC ainda e ontem em Brasilia ---

def test_hoje_em_sao_paulo_as_02h_utc_ainda_e_o_dia_anterior():
    tarde = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
    madrugada = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)
    assert hoje_em_sao_paulo(tarde) == date(2026, 10, 15)
    assert hoje_em_sao_paulo(madrugada) == date(2026, 10, 15)


def test_situacao_as_02h_utc_igual_a_das_15h_utc_do_mesmo_dia_de_brasilia():
    # Vencimento em 10/10, carencia ate 15/10: 02:00 UTC de 16/10 e 23:00 de
    # 15/10 em Brasilia, ainda atrasada e nao bloqueada.
    tarde = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
    madrugada = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)
    leituras = [
        ler_situacao(
            barbearia_ativa=True, isenta=False, nunca_bloquear=False,
            paga_ate=PAGA_ATE, aviso_em=None,
            hoje=hoje_em_sao_paulo(agora), agora=agora,
        )
        for agora in (tarde, madrugada)
    ]
    assert leituras[0] == leituras[1]
    assert (leituras[1].situacao, leituras[1].dias) == (Situacao.ATRASADA, 5)


# --- novo_paga_ate ---

def test_em_dia_ou_na_carencia_mantem_o_dia():
    assert novo_paga_ate(
        paga_ate=date(2026, 10, 10), dia_de_vencimento=10,
        estava_bloqueada=False, hoje=date(2026, 10, 12),
    ) == (date(2026, 11, 10), 10)


def test_dezembro_vira_janeiro():
    assert novo_paga_ate(
        paga_ate=date(2026, 12, 20), dia_de_vencimento=20,
        estava_bloqueada=False, hoje=date(2026, 12, 20),
    ) == (date(2027, 1, 20), 20)


def test_bloqueada_recomeca_de_hoje():
    assert novo_paga_ate(
        paga_ate=date(2026, 9, 1), dia_de_vencimento=1,
        estava_bloqueada=True, hoje=date(2026, 10, 30),
    ) == (date(2026, 11, 28), 28)
