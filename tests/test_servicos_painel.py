import uuid

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from fabricas import criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _servico(barbearia_id, nome="Corte", ativo=True, ordem=0, min_=20, sugerida=30):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        duracao_minima_min=min_, duracao_sugerida_min=sugerida,
        ativo=ativo, ordem=ordem,
    )


def _barbeiro(barbearia_id, nome="Zeca", papel="DONO", ativo=True):
    from tenant.models import Barbeiro

    return criar_barbeiro(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=ativo,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    token = emitir(sub=barbeiro.usuario_id, bid=barbearia_id, papel=barbeiro.usuario.papel, tv=0)
    client.cookies[COOKIE_SESSAO] = token
    return host


CABECALHO = {"x-brutus-cliente": "web"}


def test_get_lista_ativos_e_inativos_com_contagem_de_barbeiros(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono")
    host = _logar(client, dono, b.id)

    servico = _servico(b.id)
    from tenant.models import BarbeiroServico

    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=dono.id, servico_id=servico.id, barbearia_id=b.id,
        duracao_min=30, ativo=True,
    )
    _servico(b.id, nome="Barba", ativo=False)

    r = client.get("/api/painel/servicos", headers={"host": host})
    assert r.status_code == 200
    nomes = {s["nome"]: s for s in r.json()["servicos"]}
    assert nomes["Corte"]["barbeiros"] == 1
    assert nomes["Barba"]["ativo"] is False


def test_get_nao_exige_ser_dono(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.get("/api/painel/servicos", headers={"host": host})
    assert r.status_code == 200


def test_get_sem_sessao_e_401(client, cenario):
    r = client.get("/api/painel/servicos", headers={"host": "brutus.localhost"})
    assert r.status_code == 401


def test_post_barbeiro_comum_recebe_403_com_a_frase_do_catalogo(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.post(
        "/api/painel/servicos",
        {"nome": "Sobrancelha", "duracaoMinimaMin": 10, "duracaoSugeridaMin": 15},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono mexe no catálogo."


def test_post_cria_com_ordem_seguinte_a_ultima(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    _servico(b.id, nome="Corte", ordem=3)

    r = client.post(
        "/api/painel/servicos",
        {"nome": "Barba", "duracaoMinimaMin": 10, "duracaoSugeridaMin": 20},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201

    from tenant.models import Servico

    criado = Servico.objects.using("owner").get(id=r.json()["id"])
    assert criado.ordem == 4


def test_post_nome_repetido_ativo_da_409(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    _servico(b.id, nome="Corte")

    r = client.post(
        "/api/painel/servicos",
        {"nome": "Corte", "duracaoMinimaMin": 10, "duracaoSugeridaMin": 20},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "desativado" not in r.json()["erro"]


def test_post_nome_repetido_desativado_avisa_para_reativar(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    _servico(b.id, nome="Corte", ativo=False)

    r = client.post(
        "/api/painel/servicos",
        {"nome": "Corte", "duracaoMinimaMin": 10, "duracaoSugeridaMin": 20},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "Reativa" in r.json()["erro"]


def test_post_duracao_fora_dos_limites_e_422(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)

    r = client.post(
        "/api/painel/servicos",
        {"nome": "Corte", "duracaoMinimaMin": 5, "duracaoSugeridaMin": 20},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_patch_atualiza_e_404_para_id_inexistente(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    servico = _servico(b.id)

    r = client.patch(
        f"/api/painel/servicos/{servico.id}",
        {"ativo": False},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    r2 = client.patch(
        "/api/painel/servicos/nao-existe",
        {"ativo": False},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r2.status_code == 404


def test_patch_nome_para_um_ja_existente_da_409(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    _servico(b.id, nome="Corte")
    barba = _servico(b.id, nome="Barba")

    r = client.patch(
        f"/api/painel/servicos/{barba.id}",
        {"nome": "Corte"},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409


def test_patch_confere_limites_com_o_estado_final_mesclado(client, cenario):
    """Subir a minima sem mexer na sugerida pode inverter as duas — os
    limites tem que ser conferidos com o valor final, nao so o que veio."""
    b = cenario["brutus"]
    dono = _barbeiro(b.id)
    host = _logar(client, dono, b.id)
    servico = _servico(b.id, min_=20, sugerida=30)

    r = client.patch(
        f"/api/painel/servicos/{servico.id}",
        {"duracaoMinimaMin": 40},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_o_rls_isola_a_leitura_do_catalogo(client, cenario):
    for slug, nome in (("brutus", "Corte"), ("dontony", "Barba")):
        _servico(cenario[slug].id, nome=nome)

    dono = _barbeiro(cenario["brutus"].id)
    host = _logar(client, dono, cenario["brutus"].id)

    nomes = [s["nome"] for s in client.get("/api/painel/servicos", headers={"host": host}).json()["servicos"]]
    assert nomes == ["Corte"]
