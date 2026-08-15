import uuid

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _servico(barbearia_id, nome="Corte", ativo=True, min_=20, sugerida=30):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        duracao_minima_min=min_, duracao_sugerida_min=sugerida, ativo=ativo,
    )


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    token = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0)
    client.cookies[COOKIE_SESSAO] = token
    return host


def test_get_lista_todos_ativos_com_faz_falso_quando_sem_vinculo(client, cenario):
    """Sem vinculo o servico ainda aparece (faz=False, com a duracao
    SUGERIDA) — 'nao veio' seria ambiguo com 'nao faz'."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico(b.id, nome="Corte", min_=20, sugerida=25)

    r = client.get(
        "/api/painel/barbeiro-servicos", {"barbeiroId": barbeiro.id},
        headers={"host": host},
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["barbeiroId"] == barbeiro.id
    assert corpo["vinculos"] == [
        {
            "servicoId": servico.id, "nome": "Corte", "duracaoMinimaMin": 20,
            "faz": False, "duracaoMin": 25,
        }
    ]


def test_get_barbeiro_pedindo_o_do_colega_recebe_404(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, nome="Eu")
    colega = _barbeiro(b.id, nome="Colega")
    host = _logar(client, eu, b.id)

    r = client.get(
        "/api/painel/barbeiro-servicos", {"barbeiroId": colega.id},
        headers={"host": host},
    )
    assert r.status_code == 404


def test_get_dono_ve_o_de_qualquer_um(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, nome="Dono", papel="DONO")
    colega = _barbeiro(b.id, nome="Colega")
    host = _logar(client, dono, b.id)

    r = client.get(
        "/api/painel/barbeiro-servicos", {"barbeiroId": colega.id},
        headers={"host": host},
    )
    assert r.status_code == 200
    assert r.json()["barbeiroId"] == colega.id


def test_put_marca_com_duracao_sugerida_quando_nao_informada(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico(b.id, sugerida=25)

    r = client.put(
        "/api/painel/barbeiro-servicos",
        {"servicoId": servico.id, "faz": True},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import BarbeiroServico

    vinculo = BarbeiroServico.objects.using("owner").get(
        barbeiro_id=barbeiro.id, servico_id=servico.id
    )
    assert vinculo.duracao_min == 25
    assert vinculo.ativo is True


def test_put_desmarcar_preserva_a_duracao_praticada(client, cenario):
    """Desmarcar e' `ativo=False`, nunca DELETE — remarcar tem que devolver o
    numero que era, nao a sugerida de novo."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico(b.id, sugerida=25)

    from tenant.models import BarbeiroServico

    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=b.id,
        duracao_min=40, ativo=True,
    )

    r = client.put(
        "/api/painel/barbeiro-servicos",
        {"servicoId": servico.id, "faz": False},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    vinculo = BarbeiroServico.objects.using("owner").get(
        barbeiro_id=barbeiro.id, servico_id=servico.id
    )
    assert vinculo.duracao_min == 40
    assert vinculo.ativo is False


def test_put_duracao_abaixo_da_minima_do_servico_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico(b.id, min_=20, sugerida=30)

    r = client.put(
        "/api/painel/barbeiro-servicos",
        {"servicoId": servico.id, "faz": True, "duracaoMin": 15},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_put_servico_inexistente_e_404(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.put(
        "/api/painel/barbeiro-servicos",
        {"servicoId": "nao-existe", "faz": True},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404


def test_put_dois_servicos_do_mesmo_barbeiro_nao_se_confundem(client, cenario):
    """A prova de que `definir_vinculo` filtra pelos dois campos, nao pela pk
    sozinha: mexer no vinculo do segundo servico nao pode tocar o primeiro."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    corte = _servico(b.id, nome="Corte", sugerida=30)
    barba = _servico(b.id, nome="Barba", min_=10, sugerida=15)

    for servico in (corte, barba):
        client.put(
            "/api/painel/barbeiro-servicos",
            {"servicoId": servico.id, "faz": True},
            content_type="application/json",
            headers={"host": host, **CABECALHO},
        )

    r = client.put(
        "/api/painel/barbeiro-servicos",
        {"servicoId": barba.id, "faz": False, "duracaoMin": 20},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import BarbeiroServico

    vinculo_corte = BarbeiroServico.objects.using("owner").get(
        barbeiro_id=barbeiro.id, servico_id=corte.id
    )
    vinculo_barba = BarbeiroServico.objects.using("owner").get(
        barbeiro_id=barbeiro.id, servico_id=barba.id
    )
    assert vinculo_corte.ativo is True and vinculo_corte.duracao_min == 30
    assert vinculo_barba.ativo is False and vinculo_barba.duracao_min == 20
