import re
import uuid

import pytest
from django.contrib.auth.models import User
from django.test import Client

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


def _requisicao_admin(sessao_dados=None, caminho="/admin/django/"):
    """Monta uma requisicao GET sob o prefixo do admin, com o cookie da
    plataforma e (opcionalmente) `barbearia_escolhida` na sessao — o minimo
    que `AdminDjangoMiddleware` precisa pra decidir alguma coisa, sem passar
    pela pilha inteira de middlewares (por isso RequestFactory, e nao
    `client`).

    `caminho` importa desde que o middleware passou a REDIRECIONAR para o
    seletor quando nao ha barbearia escolhida: para exercitar o caminho em que
    ele segue em frente sem definir a variavel, a requisicao precisa apontar
    para um dos caminhos de `SEM_ESCOLHA`."""
    from django.contrib.sessions.backends.db import SessionStore
    from django.test import RequestFactory

    sessao = SessionStore()
    if sessao_dados:
        for chave, valor in sessao_dados.items():
            sessao[chave] = valor
        sessao.save()

    req = RequestFactory().get(caminho)
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

    # O seletor: um dos caminhos que funcionam SEM barbearia escolhida. Sem
    # isto o middleware redirecionaria e `leitor_segunda` nunca rodaria — o
    # teste passaria a nao afirmar nada sobre vazamento, que e' o ponto dele.
    segunda = _requisicao_admin(caminho=AdminDjangoMiddleware.CAMINHO_DO_SELETOR)
    AdminDjangoMiddleware(leitor_segunda)(segunda)

    assert lido_segunda["valor"] in (None, "")


# --------------------------------------------------------- o seletor


def _barbearia_id(cenario, slug="brutus"):
    return str(cenario[slug].id)


def test_o_seletor_lista_as_barbearias(client, cenario):
    _logar_admin(client)
    r = client.get("/admin/django/escolher-barbearia", headers={"host": HOST_ADMIN})
    assert r.status_code == 200
    corpo = r.content.decode()
    assert "brutus" in corpo and "dontony" in corpo


def test_escolher_grava_na_sessao(client, cenario):
    _logar_admin(client)
    alvo = _barbearia_id(cenario)
    r = client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": alvo},
        headers={"host": HOST_ADMIN},
    )
    assert r.status_code == 302
    assert client.session["barbearia_escolhida"] == alvo


def test_o_seletor_tambem_esta_atras_da_porta(client, cenario):
    """Ele esta sob o mesmo prefixo, entao herda a barreira sem pedir. Sem
    este teste, uma rota nova sob /admin/django podia nascer aberta e ninguem
    perceberia."""
    r = client.get("/admin/django/escolher-barbearia", headers={"host": HOST_ADMIN})
    assert r.status_code == 404


def test_id_que_nao_existe_nao_e_gravado(client, cenario):
    """Gravar um id qualquer deixaria o admin num estado em que toda lista vem
    vazia e nada explica por que."""
    _logar_admin(client)
    r = client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": str(uuid.uuid4())},
        headers={"host": HOST_ADMIN},
    )
    assert r.status_code == 400
    assert "barbearia_escolhida" not in client.session


def test_o_formulario_leva_o_token_csrf_e_o_post_sem_ele_e_recusado(client, cenario):
    """O client de teste padrao (`client`, acima) desliga a checagem de CSRF —
    e' por isso que `test_escolher_grava_na_sessao` passaria verde mesmo se o
    `<form>` nao emitisse `csrfmiddlewaretoken`, escondendo exatamente o
    defeito que quebraria o seletor no navegador de verdade (403 "CSRF
    verification failed", porque `CsrfViewMiddleware` e' global desde a Task 1
    e esta view nao e' `csrf_exempt`). Este teste existe para pegar isso: liga
    a checagem (`enforce_csrf_checks=True`) e prova as DUAS pontas — sem o
    token o POST leva 403 (o controle negativo), e com o token tirado do
    proprio HTML que a view devolveu o POST grava na sessao. Sem o controle
    negativo, nao daria para distinguir "o token era necessario" de "o token
    era irrelevante"."""
    rigoroso = Client(enforce_csrf_checks=True)
    _logar_admin(rigoroso)
    alvo = _barbearia_id(cenario)

    # Controle negativo: sem o token, com a checagem ligada, tem que ser
    # recusado. Sem esta linha o teste provaria so' que o caminho feliz
    # funciona, nao que o token e' o que protege.
    sem_token = rigoroso.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": alvo},
        headers={"host": HOST_ADMIN},
    )
    assert sem_token.status_code == 403
    # Amarra o 403 a' CAUSA certa: se algum dia sumir a isencao de
    # `/admin/django` no `ClienteMiddleware`, o POST tambem levaria 403 -- mas
    # por falta de `X-Brutus-Cliente`, nao por falta de token CSRF, e o
    # navegador quebraria por um motivo que este teste nao pegaria sem esta
    # linha (continuaria verde, pelo motivo errado).
    assert b"CSRF" in sem_token.content
    assert b"pedido sem cliente" not in sem_token.content

    r = rigoroso.get("/admin/django/escolher-barbearia", headers={"host": HOST_ADMIN})
    assert r.status_code == 200
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.content.decode()).group(1)

    com_token = rigoroso.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": alvo, "csrfmiddlewaretoken": token},
        headers={"host": HOST_ADMIN},
    )
    assert com_token.status_code == 302
    assert rigoroso.session["barbearia_escolhida"] == alvo


# ------------------------------------------- rodada de correcao 1 (revisao)


@pytest.mark.parametrize(
    "dados",
    [
        pytest.param({}, id="campo_ausente"),
        pytest.param({"barbearia_id": "lixo"}, id="texto_solto"),
        pytest.param({"barbearia_id": "'; DROP TABLE x; --"}, id="tentativa_de_sql"),
    ],
)
def test_id_malformado_nao_derruba_a_view(client, cenario, dados):
    """`Barbearia.id` e' UUIDField, e `request.POST.get("barbearia_id") or ""`
    transforma campo ausente em `""` -- que, igual a "lixo" e a uma tentativa
    de SQL, nao parseia como UUID. Sem validar a FORMA antes do `filter`, o
    Django levanta `ValidationError` DENTRO do ORM, antes de qualquer SQL
    rodar, e a view devolve 500 em vez do 400 que um UUID bem formado mas
    inexistente ja recebe. As duas perguntas ("essa barbearia existe?" e
    "isso e' um UUID?") tem a MESMA resposta pratica para quem preenche o
    formulario: nao ha barbearia para esse valor."""
    _logar_admin(client)
    r = client.post(
        "/admin/django/escolher-barbearia",
        dados,
        headers={"host": HOST_ADMIN},
    )
    assert r.status_code == 400
    assert "barbearia_escolhida" not in client.session


def test_a_sessao_grava_a_forma_canonica_do_uuid(client, cenario):
    """A politica de RLS compara `barbearia_id::text` (ver
    `tenant/migrations/0002_rls.py`) contra `current_setting('app.barbearia_id',
    true)`, e o `::text` do Postgres sempre devolve a forma CANONICA --
    minuscula, com hifens. Gravar na sessao o texto CRU do POST deixaria
    passar formas equivalentes mas que o `::text` nunca vai igualar
    (maiusculo, sem hifen, `urn:uuid:...`): o `filter(id=...)` do Django
    normaliza antes de consultar e aceita todas elas, entao o POST responde
    302 alegre, a sessao grava a forma errada, e o admin cai no mesmo "toda
    lista vem vazia e nada explica por que" que a validacao de existencia
    tenta evitar. Postar em MAIUSCULO e' o jeito mais direto de provar isso:
    se a sessao guardasse o texto cru, esta asserção falharia."""
    _logar_admin(client)
    alvo = _barbearia_id(cenario)
    r = client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": alvo.upper()},
        headers={"host": HOST_ADMIN},
    )
    assert r.status_code == 302
    assert client.session["barbearia_escolhida"] == alvo


def test_o_seletor_tambem_responde_com_a_barra_no_final(client, cenario):
    """O `catch_all_view` de `admin.site.urls` engole qualquer caminho que
    sobre sob `/admin/django/` e devolve 302 para o login do Django sem
    explicar nada -- quem digitar a URL com barra cairia nisso se a rota so'
    estivesse registrada sem barra. `APPEND_SLASH` nao ajuda porque o
    catch-all resolve ANTES dele ter chance de agir."""
    _logar_admin(client)
    r = client.get("/admin/django/escolher-barbearia/", headers={"host": HOST_ADMIN})
    assert r.status_code == 200


def test_barbearia_inativa_aparece_marcada(client, cenario):
    """Uma barbearia inativa e' recusada pelo `TenantMiddleware` em producao
    (`_buscar_por_slug` filtra `ativo=True`): escolhe-la aqui da' um admin
    funcional sobre um tenant que, do lado do subdominio, nao existe. Listar
    todas continua certo -- e' a ferramenta do dono da plataforma, e o brief
    manda assim -- mas sem o aviso ninguem notaria o descompasso antes de
    mexer em dado de uma barbearia que o publico nao alcanca mais."""
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").create(
        id=str(uuid.uuid4()),
        slug="zumbi",
        nome="Zumbi Barbearia",
        endereco="Rua Aurora, 88",
        horario_resumo=None,
        whatsapp_contato="11900000000",
        ativo=False,
        criado_em="2026-08-11T12:00:00Z",
    )
    _logar_admin(client)
    r = client.get("/admin/django/escolher-barbearia", headers={"host": HOST_ADMIN})
    corpo = r.content.decode()
    assert "zumbi" in corpo
    assert "(inativa)" in corpo


# ------------------------------------------------------ os ModelAdmin (task 4)


def _logar_django(client):
    """Superusuario com nome unico por teste: o `limpar_banco` do conftest
    trunca so' as tabelas de tenant, entao `auth_user` sobrevive entre casos e
    um nome fixo colidiria na segunda vez."""
    nome = f"admin-{uuid.uuid4().hex[:8]}"
    User.objects.create_superuser(username=nome, email="", password="senha-de-teste")
    client.login(username=nome, password="senha-de-teste")


def _cliente(barbearia_id, nome):
    from tenant.models import Cliente

    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )


def test_o_admin_nao_ve_dado_de_outra_barbearia(client, cenario):
    """O TESTE DESTA ETAPA. Se ele nao existir, o resto nao vale nada: o
    admin do Django e' uma tela que lista qualquer tabela, e a unica coisa
    entre ela e o dado de outra barbearia e' a politica do Postgres."""
    b, d = cenario["brutus"], cenario["dontony"]
    _cliente(b.id, "Cliente do Brutus")
    _cliente(d.id, "Cliente do Dom Tony")

    _logar_admin(client)
    _logar_django(client)
    client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": str(b.id)},
        headers={"host": HOST_ADMIN},
    )

    r = client.get("/admin/django/tenant/cliente/", headers={"host": HOST_ADMIN})
    assert r.status_code == 200
    corpo = r.content.decode()
    assert "Cliente do Brutus" in corpo
    assert "Cliente do Dom Tony" not in corpo


def test_sem_escolher_barbearia_o_admin_manda_escolher(client, cenario):
    """Antes esta tela vinha VAZIA — sete secoes com zero linha e nada
    explicando por que (a politica de RLS nao casa com linha nenhuma sem a
    variavel definida). Foi o primeiro tropeco de quem usou o admin de
    verdade: "nao tem barbeiro aqui". Havia tres; faltava dizer de qual
    barbearia.

    Agora o middleware manda para o seletor. Nao da' para se perder numa tela
    que so' tem um caminho."""
    _cliente(cenario["brutus"].id, "Cliente do Brutus")
    _logar_admin(client)
    _logar_django(client)

    r = client.get("/admin/django/tenant/cliente/", headers={"host": HOST_ADMIN})
    assert r.status_code == 302
    assert r["Location"] == "/admin/django/escolher-barbearia"


def test_o_seletor_e_o_login_escapam_do_redirecionamento(client, cenario):
    """Sem esta isencao os tres se apontariam em circulo: o seletor mandaria
    para si mesmo, e o login (que tambem roda sem barbearia escolhida) mandaria
    para o seletor, que mandaria para o login por falta de sessao do Django.
    Tres telas, nenhuma alcancavel."""
    _logar_admin(client)
    for caminho in ("/admin/django/escolher-barbearia", "/admin/django/login/"):
        r = client.get(caminho, headers={"host": HOST_ADMIN})
        assert r.status_code == 200, caminho


def test_barbearia_e_editavel_e_apagar_esta_ligado(client, cenario):
    """O dono da plataforma pediu o admin com TUDO ativo, e a decisao e' dele:
    e' a ferramenta dele, e um admin que esconde metade dos botoes obriga a
    sair dele para trabalhar.

    O que este teste NAO promete, e esta escrito no docstring de
    `BarbeariaAdmin`: criar barbearia por aqui produz uma barbearia ORFA (sem
    dono e sem convite), porque o "adicionar" do Django faz um INSERT e mais
    nada. Criar continua sendo pelo painel da plataforma."""
    _logar_admin(client)
    _logar_django(client)
    escolher = client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": str(cenario["brutus"].id)},
        headers={"host": HOST_ADMIN},
    )
    assert escolher.status_code == 302

    assert client.get(
        "/admin/django/tenant/barbearia/add/", headers={"host": HOST_ADMIN}
    ).status_code == 200

    # E apagar deixou de ser recusado nos models de tenant. Instanciado de
    # verdade (o ModelAdmin precisa do model e do site) — chamar o metodo na
    # classe passaria a propria classe como `self` e estouraria em `opts`.
    from django.contrib import admin as admin_do_django

    from app.admin import BarbeiroAdmin
    from tenant.models import Barbeiro

    pedido = client.get("/admin/django/tenant/barbeiro/", headers={"host": HOST_ADMIN}).wsgi_request
    assert BarbeiroAdmin(Barbeiro, admin_do_django.site).has_delete_permission(pedido) is True


def test_a_barbearia_aparece_pelo_nome_e_nao_pelo_uuid(client, cenario):
    """`Barbearia object (uuid)` era o que a tela mostrava em todo <select> de
    chave estrangeira e em todo cabecalho de formulario — um uuid nao
    identifica nada para quem esta olhando."""
    assert str(cenario["brutus"]) == "Brutus"

    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=cenario["brutus"].id).first()
    assert str(barbeiro) == barbeiro.nome
