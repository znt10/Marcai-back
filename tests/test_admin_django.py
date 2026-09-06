import uuid

import pytest

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir

pytestmark = pytest.mark.django_db(
    databases=["default", "owner", "admin"], transaction=True
)

HOST_ADMIN = "admin.localhost"
HOST_BARBEARIA = "brutus.localhost"


def _logar_admin(client):
    """O cookie da plataforma — o mesmo que o painel custom emite."""
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()


def test_de_host_de_barbearia_o_admin_nao_existe(client, cenario):
    """404 e nao 403, e nao a tela de login: 403 confirmaria que o recurso
    existe. Quem recusa aqui e' o `BarreiraAdminMiddleware`, por POSICAO —
    esta rota nao precisou pedir protecao nenhuma."""
    r = client.get("/admin/django/", headers={"host": HOST_BARBEARIA})
    assert r.status_code == 404


def test_sem_o_cookie_da_plataforma_o_admin_nao_existe(client, cenario):
    """Mesmo do host certo. E' esta linha que faz o admin ser SO' do dono da
    plataforma: barbeiro nenhum tem este cookie, e nao tem como obter um."""
    r = client.get("/admin/django/", headers={"host": HOST_ADMIN})
    assert r.status_code == 404


def test_com_o_cookie_o_admin_responde(client, cenario):
    """Responde a tela de login do Django — o cookie abre a porta, nao a
    sessao."""
    _logar_admin(client)
    r = client.get("/admin/django/", headers={"host": HOST_ADMIN})
    assert r.status_code in (200, 302)


def test_o_middleware_nao_toca_no_resto_do_sistema(client, cenario):
    """Fora do prefixo ele sai na primeira linha. Sem esta garantia, toda
    requisicao da API passaria a rodar dentro de uma transacao aberta pelo
    middleware — mudanca de comportamento que ninguem pediu.

    Host explicito (`HOST_BARBEARIA`), como todo teste que bate em
    `/api/saude`: sem `host`, o client de teste usa `testserver`, e o
    `TenantMiddleware` levantaria 404 por conta propria, por nao achar slug
    nenhum — um sintoma que nao teria nada a ver com o middleware desta task.
    """
    r = client.get("/api/saude", headers={"host": HOST_BARBEARIA})
    assert r.status_code == 200


def test_post_do_admin_nao_leva_403_por_falta_de_header(client, cenario):
    """O admin do Django faz POST de formulario HTML, sem `X-Brutus-Cliente`.
    Sem a isencao do `ClienteMiddleware`, o LOGIN dele ja levaria 403 e o admin
    seria inutil — e o sintoma nao mencionaria header nenhum.

    O 404 aqui e' da porta (sem cookie), e nao o 403 do ClienteMiddleware: e'
    exatamente essa distincao que o teste afirma. Sem a isencao, o
    ClienteMiddleware responderia PRIMEIRO, porque esta antes na lista.
    """
    r = client.post(
        "/admin/django/login/", {"username": "x", "password": "y"},
        headers={"host": HOST_ADMIN},
    )
    assert r.status_code == 404
    assert r.status_code != 403
