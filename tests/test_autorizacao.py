import uuid

from app.services.autorizacao import alvo_do_barbeiro, filtro_do_barbeiro

# Os ids sao `uuid.UUID`, e nao mais apelidos como "d1"/"f1", porque desde a
# fatia 1 e' isso que a sessao carrega: `sessao.ler()` converte `sub` e `bid` na
# entrada e RECUSA um token cujos claims nao tenham forma de uuid. Um fixture
# com "d1" testaria uma sessao que o sistema nao consegue mais produzir — e
# esconderia justamente o descasamento texto/uuid que estas funcoes tem de
# atravessar, porque o `pedido` continua chegando da query como TEXTO.
D1 = uuid.uuid4()      # o dono
F1 = uuid.uuid4()      # o barbeiro comum
OUTRO = uuid.uuid4()   # um terceiro qualquer
COLEGA = uuid.uuid4()  # o barbeiro do lado

DONO = {"sub": D1, "bid": uuid.uuid4(), "papel": "DONO", "tv": 0}
BARBEIRO = {"sub": F1, "bid": uuid.uuid4(), "papel": "BARBEIRO", "tv": 0}


def test_filtro_do_dono_e_vazio():
    """Dono ve tudo: nenhum filtro de barbeiro entra na consulta."""
    assert filtro_do_barbeiro(DONO) == {}


def test_filtro_do_barbeiro_e_o_proprio_id():
    assert filtro_do_barbeiro(BARBEIRO) == {"barbeiro_id": F1}


def test_alvo_do_dono_sem_pedido_e_ele_mesmo():
    """Sem `barbeiroId` na query, o dono ve a propria coluna — comportamento
    do quadro do dia e da agenda quando ninguem pediu um barbeiro especifico.
    """
    assert alvo_do_barbeiro(DONO, None) == D1


def test_alvo_do_dono_com_pedido_e_o_pedido():
    assert alvo_do_barbeiro(DONO, str(OUTRO)) == OUTRO


def test_alvo_do_barbeiro_sem_pedido_e_ele_mesmo():
    assert alvo_do_barbeiro(BARBEIRO, None) == F1


def test_alvo_do_barbeiro_pedindo_o_proprio_id_e_ele_mesmo():
    """O caso que o descasamento texto/uuid quebraria PRIMEIRO, e da forma mais
    cara: o `pedido` vem da query como texto e o `sub` e' UUID, entao sem a
    conversao os dois nunca sao iguais e o barbeiro leva 404 no PROPRIO
    registro — a rota recusando exatamente quem tem direito.
    """
    assert alvo_do_barbeiro(BARBEIRO, str(F1)) == F1


def test_alvo_do_barbeiro_pedindo_o_do_colega_e_none():
    """None e o sinal para a rota responder 404: registro alheio, o status
    nao pode confirmar que existe."""
    assert alvo_do_barbeiro(BARBEIRO, str(COLEGA)) is None


def test_pedido_sem_forma_de_uuid_e_none_para_os_dois_papeis():
    """Um `?barbeiroId=nao-existe` recebe o MESMO None de um id de colega.

    Distinguir "id impossivel" de "id que nao e seu" contaria a quem chuta ids
    qual das duas coisas aconteceu. E para o DONO a resposta importa por um
    segundo motivo: sem este ramo o valor cairia no `or sessao["sub"]` e ele
    receberia os PROPRIOS dados no lugar de um vazio — dado que ninguem pediu,
    com cara de resposta certa.
    """
    assert alvo_do_barbeiro(DONO, "nao-existe") is None
    assert alvo_do_barbeiro(BARBEIRO, "nao-existe") is None
