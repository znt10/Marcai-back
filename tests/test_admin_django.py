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
    # `!= 403` nao afirma nada aqui — ja' sabemos que e' 404 pela linha
    # acima, entao `!= 403` nunca poderia falhar. A afirmacao de verdade e'
    # que o corpo nao e' o do `ClienteMiddleware`: se a isencao sumisse, o
    # 403 dele viria com este texto (`JsonResponse({"erro": "pedido sem
    # cliente"}, ...)`), e esta linha pegaria isso mesmo se, por acidente,
    # outro codigo tambem devolvesse 404.
    assert b"pedido sem cliente" not in r.content


# --------------------------------------------------------- o escopo (RLS)


def _requisicao_admin(sessao_dados=None):
    """Monta uma requisicao GET sob o prefixo do admin, com o cookie da
    plataforma e (opcionalmente) `barbearia_escolhida` na sessao — o minimo
    que `AdminDjangoMiddleware` precisa pra decidir alguma coisa, sem passar
    pela pilha inteira de middlewares (por isso RequestFactory, e nao
    `client`)."""
    from django.contrib.sessions.backends.db import SessionStore
    from django.test import RequestFactory

    sessao = SessionStore()
    if sessao_dados:
        for chave, valor in sessao_dados.items():
            sessao[chave] = valor
        sessao.save()

    req = RequestFactory().get("/admin/django/")
    req.COOKIES = {COOKIE_SESSAO_ADMIN: emitir()}
    req.session = sessao
    return req


def _current_setting():
    """Le `app.barbearia_id` na conexao `default` — a MESMA que o middleware
    usa. Fora de qualquer `with com_barbearia_por_requisicao(...)`, e' o
    valor que o RLS de verdade enxergaria."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('app.barbearia_id', true)")
        return cur.fetchone()[0]


def test_o_escopo_define_app_barbearia_id_durante_a_requisicao(client, cenario):
    """A metade 'escopo' da task, sem a qual `com_barbearia_por_requisicao'
    e' codigo morto do ponto de vista da suite: nenhum outro teste chama o
    middleware com uma `barbearia_escolhida` na sessao e confere o que o RLS
    veria. Apagar as seis linhas de escopo em `AdminDjangoMiddleware.__call__`
    (deixando so' `return self.get_response(request)`) faz esta afirmacao
    falhar na hora — `lido["valor"]` viria vazio, nao o id da Brutus."""
    from tenant.middleware import AdminDjangoMiddleware

    lido = {}

    def get_response(request):
        lido["valor"] = _current_setting()
        return None

    req = _requisicao_admin({AdminDjangoMiddleware.CHAVE_SESSAO: str(cenario["brutus"].id)})
    AdminDjangoMiddleware(get_response)(req)

    assert lido["valor"] == str(cenario["brutus"].id)


def test_a_variavel_de_rls_morre_com_a_transacao(client, cenario):
    """Defende o `is_local=true` do `set_config` em
    `com_barbearia_por_requisicao`: trocar para `false` faria a variavel
    viver na SESSAO do Postgres em vez da transacao — e como a conexao volta
    para a pool, o PROXIMO pedido herdaria o tenant deste. Vazamento cruzado
    entre barbearias, intermitente, sem erro nenhum, e nenhum teste que olhe
    uma requisicao so' pegaria isso.

    A primeira asserção e' so' sanidade (confirma que o bloco rodou, para a
    segunda nao passar por acidente com a variavel nunca tendo sido
    definida); a segunda e' a que importa: DEPOIS que o `with` sai, a mesma
    conexao nao pode mais devolver o id."""
    from tenant.middleware import AdminDjangoMiddleware

    lido = {}

    def get_response(request):
        lido["durante"] = _current_setting()
        return None

    req = _requisicao_admin({AdminDjangoMiddleware.CHAVE_SESSAO: str(cenario["brutus"].id)})
    AdminDjangoMiddleware(get_response)(req)

    assert lido["durante"] == str(cenario["brutus"].id)
    assert _current_setting() in (None, "")


def test_requisicao_seguinte_sem_escolha_nao_herda_a_anterior(client, cenario):
    """A consequencia pratica do teste acima: nao basta a variavel morrer em
    teoria, o PROXIMO pedido tem que de fato nao ver o id do anterior. Sem
    `barbearia_escolhida` na segunda sessao, o middleware nem entra no bloco
    `com_barbearia_por_requisicao` — a leitura tem que vir vazia, e nao o id
    da Brutus deixado pela primeira requisicao."""
    from tenant.middleware import AdminDjangoMiddleware

    lido_primeira = {}

    def leitor_primeira(request):
        lido_primeira["valor"] = _current_setting()
        return None

    primeira = _requisicao_admin({AdminDjangoMiddleware.CHAVE_SESSAO: str(cenario["brutus"].id)})
    AdminDjangoMiddleware(leitor_primeira)(primeira)
    assert lido_primeira["valor"] == str(cenario["brutus"].id)

    lido_segunda = {}

    def leitor_segunda(request):
        lido_segunda["valor"] = _current_setting()
        return None

    segunda = _requisicao_admin()  # sem barbearia_escolhida
    AdminDjangoMiddleware(leitor_segunda)(segunda)

    assert lido_segunda["valor"] in (None, "")
