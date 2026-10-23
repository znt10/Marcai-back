import pytest

from app.services.mensalidade.centavos import SemCentavoLivre, escolher


def test_sem_ocupados_soma_um_centavo():
    assert escolher(3500, set()) == 3501


def test_pula_o_centavo_ocupado():
    assert escolher(3500, {3501}) == 3502


def test_pega_o_menor_livre_mesmo_com_buraco():
    assert escolher(3500, {3501, 3503}) == 3502


def test_nunca_devolve_o_valor_base():
    # O valor cheio, sem centavo, e do pagamento "avulso" da chave: nao entra.
    assert escolher(3500, {3500}) == 3501


def test_valor_ocupado_de_outra_faixa_nao_atrapalha():
    assert escolher(3500, {4001, 3600}) == 3501


def test_ultimo_centavo_livre_e_99():
    ocupados = {3500 + k for k in range(1, 99)}
    assert escolher(3500, ocupados) == 3599


def test_todos_ocupados_levanta():
    ocupados = {3500 + k for k in range(1, 100)}
    with pytest.raises(SemCentavoLivre):
        escolher(3500, ocupados)
