"""GET/PUT /api/painel/meu-pix — a cobranca no agendamento de CADA barbeiro."""

import uuid

import pytest

from tenant.models import Barbeiro, BarbeiroServico, Servico

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/painel/meu-pix"
CABECALHO = {"x-brutus-cliente": "web"}
CHAVE = "fulano@exemplo.com"
T = {"pixTipo": "EMAIL"}


def _barbeiro(barbearia_id, papel="BARBEIRO", **extra):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"{papel} teste",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True, **extra,
    )


def _logar(client, barbeiro, barbearia):
    from app.services.sessao import COOKIE_SESSAO, emitir

    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia.id, papel=barbeiro.papel, tv=barbeiro.token_version,
    )
    return {"host": f"{barbearia.slug}.localhost", **CABECALHO}


def _servico(barbearia_id, barbeiro, nome="Corte", preco=3500, ativo_servico=True, ativo=True):
    s = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        duracao_minima_min=30, duracao_sugerida_min=30, ativo=ativo_servico,
    )
    BarbeiroServico.objects.using("owner").create(
        barbearia_id=barbearia_id, barbeiro=barbeiro, servico=s,
        duracao_min=30, preco_centavos=preco, ativo=ativo,
    )
    return s


def _put(client, host, corpo):
    return client.put(ROTA, corpo, content_type="application/json", headers=host)


def _do_banco(barbeiro):
    return Barbeiro.objects.using("owner").get(id=barbeiro.id)


def test_sem_sessao_da_401(client, cenario):
    r = client.get(ROTA, headers={"host": "brutus.localhost"})
    assert r.status_code == 401
    r = client.put(ROTA, {}, content_type="application/json",
                   headers={"host": "brutus.localhost", **CABECALHO})
    assert r.status_code == 401


def test_get_de_quem_nunca_configurou(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    r = client.get(ROTA, headers=host)
    assert r.status_code == 200
    assert r.json() == {
        "cobraNoAgendamento": False, "pixTipo": "", "pixChave": "", "pixTitular": "",
        "servicosSemPreco": [],
    }


def test_get_lista_so_servicos_ativos_sem_preco(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    _servico(b.id, barb, "Barba", preco=None)
    _servico(b.id, barb, "Corte", preco=3500)
    _servico(b.id, barb, "Pezinho", preco=None, ativo=False)
    _servico(b.id, barb, "Antigo", preco=None, ativo_servico=False)
    host = _logar(client, barb, b)
    assert client.get(ROTA, headers=host).json()["servicosSemPreco"] == ["Barba"]


def test_liga_com_chave_titular_e_precos(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    _servico(b.id, barb)
    host = _logar(client, barb, b)
    r = _put(client, host, {
        "cobraNoAgendamento": True, "pixTipo": "EMAIL", "pixChave": "  Fulano@Exemplo.COM ",
        "pixTitular": " Fulano de Tal ",
    })
    assert r.status_code == 200
    assert r.json() == {
        "cobraNoAgendamento": True, "pixTipo": "EMAIL", "pixChave": CHAVE, "pixTitular": "Fulano de Tal",
        "servicosSemPreco": [],
    }
    salvo = _do_banco(barb)
    assert salvo.cobra_no_agendamento is True and salvo.pix_chave == CHAVE
    assert client.get(ROTA, headers=host).json()["pixChave"] == CHAVE


def test_ligar_com_servico_sem_preco_da_400_e_lista(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    _servico(b.id, barb, "Barba", preco=None)
    host = _logar(client, barb, b)
    r = _put(client, host, {"cobraNoAgendamento": True, **T, "pixChave": CHAVE, "pixTitular": "Fulano"})
    assert r.status_code == 400
    assert r.json()["servicosSemPreco"] == ["Barba"]
    assert r.json()["erro"]
    salvo = _do_banco(barb)
    assert salvo.cobra_no_agendamento is False and salvo.pix_chave == ""


@pytest.mark.parametrize("corpo", [
    {"cobraNoAgendamento": True, **T, "pixTitular": "Fulano"},
    {"cobraNoAgendamento": True, **T, "pixChave": "   ", "pixTitular": "Fulano"},
    {"cobraNoAgendamento": True, **T, "pixChave": "a" * 78 + "@x.com", "pixTitular": "Fulano"},
    {"cobraNoAgendamento": True, **T, "pixChave": CHAVE},
    {"cobraNoAgendamento": True, **T, "pixChave": CHAVE, "pixTitular": "x" * 61},
    {"cobraNoAgendamento": True, **T, "pixChave": CHAVE, "pixTitular": "😀 !!"},
    {"cobraNoAgendamento": True, "pixChave": CHAVE, "pixTitular": "Fulano"},
    {"cobraNoAgendamento": True, "pixTipo": "CPF", "pixChave": "111.111.111-11", "pixTitular": "F"},
])
def test_ligar_com_chave_ou_titular_ruim_da_400(client, cenario, corpo):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    r = _put(client, host, corpo)
    assert r.status_code == 400
    assert r.json()["erro"]
    assert _do_banco(barb).cobra_no_agendamento is False


@pytest.mark.parametrize("corpo", [
    {"cobraNoAgendamento": "sim"},
    {"cobraNoAgendamento": 1},
    {"pixChave": 123},
    {"pixTitular": ["x"]},
    {"pixTipo": 5},
    {"pixChave": None},
])
def test_tipos_errados_dao_400(client, cenario, corpo):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    assert _put(client, host, corpo).status_code == 400


def test_corpo_que_nao_e_objeto_da_400(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id), b)
    assert _put(client, host, ["x"]).status_code == 400


def test_desligar_sempre_pode_e_guarda_chave_e_titular(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id, cobra_no_agendamento=True, pix_tipo="EMAIL", pix_chave=CHAVE, pix_titular="Fulano")
    _servico(b.id, barb, "Barba", preco=None)  # ficou sem preco depois
    host = _logar(client, barb, b)
    r = _put(client, host, {"cobraNoAgendamento": False})
    assert r.status_code == 200
    salvo = _do_banco(barb)
    assert salvo.cobra_no_agendamento is False
    assert salvo.pix_chave == CHAVE and salvo.pix_titular == "Fulano"


def test_desligado_aceita_rascunho_de_chave_sem_validar(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    r = _put(client, host, {**T, "pixChave": CHAVE})
    assert r.status_code == 200
    assert _do_banco(barb).pix_chave == CHAVE


def test_ligado_trocar_chave_por_vazia_da_400(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id, cobra_no_agendamento=True, pix_tipo="EMAIL", pix_chave=CHAVE, pix_titular="Fulano")
    host = _logar(client, barb, b)
    assert _put(client, host, {"pixChave": ""}).status_code == 400
    assert _do_banco(barb).pix_chave == CHAVE
    assert _put(client, host, {"pixChave": "outra@x.com"}).status_code == 200


def test_dono_so_muda_a_propria_linha(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "DONO")
    outro = _barbeiro(b.id, cobra_no_agendamento=True, pix_tipo="EMAIL", pix_chave="outro@x.com", pix_titular="Outro")
    host = _logar(client, dono, b)

    r = _put(client, host, {**T, "pixChave": CHAVE, "pixTitular": "Dono"})
    assert r.status_code == 200
    assert _do_banco(dono).pix_chave == CHAVE
    intacto = _do_banco(outro)
    assert (intacto.cobra_no_agendamento, intacto.pix_chave, intacto.pix_titular) == (
        True, "outro@x.com", "Outro",
    )
    # E o GET do dono nao mostra a chave do outro.
    assert client.get(ROTA, headers=host).json()["pixChave"] == CHAVE


def test_barbeiro_nao_ve_o_pix_de_outro_nem_da_outra_barbearia(client, cenario):
    a, c = cenario["brutus"], cenario["dontony"]
    _barbeiro(c.id, pix_chave="alheia@x.com")
    _barbeiro(a.id, pix_chave="colega@x.com")
    eu = _barbeiro(a.id, pix_tipo="EMAIL", pix_chave="minha@x.com")
    host = _logar(client, eu, a)
    assert client.get(ROTA, headers=host).json()["pixChave"] == "minha@x.com"


def test_chave_e_gravada_na_forma_padrao(client, cenario):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    r = _put(client, host, {"pixTipo": "CELULAR", "pixChave": "(83) 99999-1234"})
    assert r.status_code == 200
    assert r.json()["pixChave"] == "+5583999991234"
    r = _put(client, host, {"pixTipo": "CPF", "pixChave": "529.982.247-25"})
    assert r.json()["pixChave"] == "52998224725"
    r = _put(client, host, {"pixTipo": "CPF", "pixChave": "529.982.247-26"})
    assert r.status_code == 400 and r.json()["erro"] == "Esse CPF não é válido."
    assert _do_banco(barb).pix_chave == "52998224725"
    # chave sem tipo nao entra nem como rascunho
    r = _put(client, host, {"pixTipo": "", "pixChave": "52998224725"})
    assert r.status_code == 400


@pytest.mark.parametrize("tipo", ["BANANA", "ALEATORIA_X"])
def test_tipo_fora_da_lista_da_400_mesmo_sem_chave(client, cenario, tipo):
    b = cenario["brutus"]
    barb = _barbeiro(b.id)
    host = _logar(client, barb, b)
    r = _put(client, host, {"pixTipo": tipo})
    assert r.status_code == 400
    assert _do_banco(barb).pix_tipo == ""


def test_ligar_confere_de_novo_a_chave_gravada(client, cenario):
    # Linha com chave e sem tipo (editada fora do meu-pix): ligar nao passa.
    b = cenario["brutus"]
    barb = _barbeiro(b.id, pix_chave="(83) 99999-1234", pix_titular="Fulano")
    _servico(b.id, barb)
    host = _logar(client, barb, b)
    assert _put(client, host, {"cobraNoAgendamento": True}).status_code == 400
    assert _do_banco(barb).cobra_no_agendamento is False
