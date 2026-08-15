from app.services.autorizacao import alvo_do_barbeiro, filtro_do_barbeiro

DONO = {"sub": "d1", "bid": "b1", "papel": "DONO", "tv": 0}
BARBEIRO = {"sub": "f1", "bid": "b1", "papel": "BARBEIRO", "tv": 0}


def test_filtro_do_dono_e_vazio():
    """Dono ve tudo: nenhum filtro de barbeiro entra na consulta."""
    assert filtro_do_barbeiro(DONO) == {}


def test_filtro_do_barbeiro_e_o_proprio_id():
    assert filtro_do_barbeiro(BARBEIRO) == {"barbeiro_id": "f1"}


def test_alvo_do_dono_sem_pedido_e_ele_mesmo():
    """Sem `barbeiroId` na query, o dono ve a propria coluna — comportamento
    do quadro do dia e da agenda quando ninguem pediu um barbeiro especifico.
    """
    assert alvo_do_barbeiro(DONO, None) == "d1"


def test_alvo_do_dono_com_pedido_e_o_pedido():
    assert alvo_do_barbeiro(DONO, "outro-id") == "outro-id"


def test_alvo_do_barbeiro_sem_pedido_e_ele_mesmo():
    assert alvo_do_barbeiro(BARBEIRO, None) == "f1"


def test_alvo_do_barbeiro_pedindo_o_proprio_id_e_ele_mesmo():
    assert alvo_do_barbeiro(BARBEIRO, "f1") == "f1"


def test_alvo_do_barbeiro_pedindo_o_do_colega_e_none():
    """None e o sinal para a rota responder 404: registro alheio, o status
    nao pode confirmar que existe."""
    assert alvo_do_barbeiro(BARBEIRO, "colega-id") is None
