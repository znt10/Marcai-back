import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

SENHA = "senha-boa-123"
CABECALHO = {"x-brutus-cliente": "web"}


def _com_senha(barbearia_id, senha=SENHA, **extra):
    from app.services.senha import gerar
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome="Zeca",
        whatsapp="11988887777",
        ativo=True,
        senha_hash=gerar(senha),
        **extra,
    )


def _logar(client, host="brutus.localhost", whatsapp="11988887777", senha=SENHA):
    return client.post(
        "/api/auth/login",
        {"whatsapp": whatsapp, "senha": senha},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )


def _eu(client, host="brutus.localhost"):
    return client.get("/api/auth/eu", headers={"host": host})


# ---------------------------------------------------------------- o contrato


def test_o_token_carrega_exatamente_as_claims_do_jose():
    """O cookie e emitido por um lado e lido pelo outro durante a travessia.
    Este teste nao usa banco de proposito: ele prende o FORMATO ao que o
    front/src/lib/auth.ts ja poe no navegador de quem usa o sistema.

    Uma claim a mais nao quebraria nada; uma a menos, ou com outro nome, faz o
    `lerSessao` do outro lado devolver null — e o sintoma e "deslogado do
    nada" numa tela so, dependendo de qual lado emitiu o cookie naquele dia.
    """
    import jwt as pyjwt

    from app.services.sessao import ALGORITMO, emitir

    token = emitir(sub="b1", bid="barbearia-1", papel="DONO", tv=3)
    carga = pyjwt.decode(token, options={"verify_signature": False})

    assert set(carga) == {"sub", "bid", "papel", "tv", "iat", "exp"}
    assert carga["sub"] == "b1" and carga["bid"] == "barbearia-1"
    assert carga["papel"] == "DONO" and carga["tv"] == 3
    assert pyjwt.get_unverified_header(token)["alg"] == ALGORITMO


def test_token_assinado_com_outro_segredo_nao_vale(monkeypatch):
    """O `ADMIN_JWT_SECRET` e diferente do `SESSAO_JWT_SECRET` de proposito, e
    e ESTA linha que faz a separacao valer: um cookie de admin apresentado ao
    painel do barbeiro morre na assinatura, sem que ninguem escreva uma
    checagem para isso.
    """
    from app.services import sessao

    monkeypatch.setenv("SESSAO_JWT_SECRET", "outro-segredo")
    forjado = sessao.emitir(sub="b1", bid="x", papel="DONO", tv=0)

    monkeypatch.setenv("SESSAO_JWT_SECRET", "segredo-so-de-teste")
    assert sessao.ler(forjado) is None


def test_tv_que_nao_e_inteiro_e_recusado(monkeypatch):
    """`isinstance(True, int)` e True em Python. Sem a recusa explicita de
    bool, um `tv: true` passaria pela conferencia de tipo e depois compararia
    igual a `tokenVersion == 1` no banco — sessao valida por acidente.
    """
    import jwt as pyjwt

    from app.services.sessao import ALGORITMO, ler

    monkeypatch.setenv("SESSAO_JWT_SECRET", "segredo-so-de-teste")
    for valor in (True, "1", 1.5):
        token = pyjwt.encode(
            {"sub": "b1", "bid": "x", "papel": "DONO", "tv": valor},
            "segredo-so-de-teste",
            algorithm=ALGORITMO,
        )
        assert ler(token) is None, f"tv={valor!r} deveria ser recusado"


# ------------------------------------------------------------------- o login


def test_login_certo_devolve_nome_papel_e_planta_o_cookie(client, cenario):
    from app.services.sessao import COOKIE_SESSAO

    _com_senha(cenario["brutus"].id)

    r = _logar(client)
    assert r.status_code == 200
    assert r.json() == {"nome": "Zeca", "papel": "BARBEIRO"}

    cookie = r.cookies[COOKIE_SESSAO]
    assert cookie.value
    # httponly e o que impede um XSS de ler a sessao; sem ele o resto da
    # defesa nao vale muito.
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    # Sem `domain`: o cookie e host-only, e e isso que impede o cookie do
    # Brutus de viajar para o Dom Tony. Um `domain=.localhost` aqui daria a
    # sessao de uma barbearia para todas as outras.
    assert not cookie["domain"]


def test_o_cookie_do_login_abre_o_eu(client, cenario):
    barbeiro = _com_senha(cenario["brutus"].id)
    _logar(client)

    r = _eu(client)
    assert r.status_code == 200
    assert r.json() == {"id": barbeiro.id, "nome": "Zeca", "papel": "BARBEIRO"}


def test_senha_errada_numero_inexistente_e_sem_senha_dao_a_MESMA_resposta(
    client, cenario
):
    """A regra que impede o formulario de login de virar uma lista da equipe.
    Se os tres desfechos diferissem em status ou em texto, bastaria iterar
    numeros e ler qual resposta muda.
    """
    b = cenario["brutus"].id
    _com_senha(b)
    from tenant.models import Barbeiro

    Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=b,
        nome="Sem senha",
        whatsapp="11977776666",
        ativo=True,
    )

    errada = _logar(client, senha="chute")
    inexistente = _logar(client, whatsapp="11900000000")
    sem_senha = _logar(client, whatsapp="11977776666")

    respostas = [(r.status_code, r.json()) for r in (errada, inexistente, sem_senha)]
    assert respostas[0] == respostas[1] == respostas[2]
    assert respostas[0][0] == 401


def test_corpo_malformado_tambem_da_a_mesma_resposta(client, cenario):
    _com_senha(cenario["brutus"].id)
    esperado = _logar(client, senha="chute")

    r = client.post(
        "/api/auth/login",
        {"nada": "aqui"},
        content_type="application/json",
        headers={"host": "brutus.localhost", **CABECALHO},
    )
    assert (r.status_code, r.json()) == (esperado.status_code, esperado.json())


def test_o_numero_e_normalizado_antes_de_procurar(client, cenario):
    """Gravado como 11988887777, digitado como +55 (11) 98888-7777. Sem a
    normalizacao o barbeiro erra a senha sem ter errado a senha — e cada
    tentativa dessas conta para a trava de 5.
    """
    _com_senha(cenario["brutus"].id)
    assert _logar(client, whatsapp="+55 (11) 98888-7777").status_code == 200


def test_login_do_host_do_admin_da_404(client, cenario):
    _com_senha(cenario["brutus"].id)
    assert _logar(client, host="admin.localhost").status_code == 404


def test_escrita_sem_o_cabecalho_de_cliente_e_recusada(client, cenario):
    """O `x-brutus-cliente` obriga preflight, e preflight e o que protege a
    escrita entre 3000 e 8000 — same-site, onde o SameSite=Lax nao protege.
    """
    _com_senha(cenario["brutus"].id)
    r = client.post(
        "/api/auth/login",
        {"whatsapp": "11988887777", "senha": SENHA},
        content_type="application/json",
        headers={"host": "brutus.localhost"},
    )
    assert r.status_code == 403


# -------------------------------------------------------------------- a trava


def test_cinco_falhas_travam_a_conta_mesmo_com_a_senha_certa(client, cenario):
    """A trava e POR CONTA e mora no BANCO. O teste que vale e o da tentativa
    seguinte com a senha CERTA: se ela passasse, a trava seria decoracao.

    A 5a falha ainda responde 401, e nao 429 — e isso e o comportamento do
    route.ts, copiado de proposito. A ordem la e: confere a trava, DEPOIS
    tenta. Na 5a tentativa a trava ainda nao existe (o contador esta em 4), a
    senha erra, e so entao ela e gravada. E a 6a que bate na porta trancada.
    Nao vale "melhorar" isto sem mudar os dois lados juntos: durante a
    travessia o mesmo barbeiro pode cair num lado ou no outro, e o numero de
    tentativas que ele tem nao pode depender disso.
    """
    _com_senha(cenario["brutus"].id)

    for _ in range(5):
        assert _logar(client, senha="chute").status_code == 401

    r = _logar(client)
    assert r.status_code == 429
    assert "Muitas tentativas" in r.json()["erro"]


def test_acerto_antes_do_limite_zera_o_contador(client, cenario):
    """Quem errou quatro vezes e acertou na quinta nao pode continuar a um
    passo da trava no dia seguinte.
    """
    from tenant.models import Barbeiro

    barbeiro = _com_senha(cenario["brutus"].id)
    for _ in range(4):
        _logar(client, senha="chute")

    assert _logar(client).status_code == 200
    guardado = Barbeiro.objects.using("owner").get(id=barbeiro.id)
    assert guardado.tentativas_login == 0
    assert guardado.bloqueado_ate is None


def test_a_trava_vencida_deixa_entrar_de_novo(client, cenario):
    from django.utils import timezone

    from tenant.models import Barbeiro

    barbeiro = _com_senha(
        cenario["brutus"].id,
        tentativas_login=5,
        bloqueado_ate=timezone.now() - timedelta(minutes=1),
    )
    assert _logar(client).status_code == 200
    assert Barbeiro.objects.using("owner").get(id=barbeiro.id).tentativas_login == 0


def test_a_trava_de_um_barbeiro_nao_trava_o_outro(client, cenario):
    """Consequencia direta de a trava ser por CONTA e nao por IP: a barbearia
    inteira sai do mesmo IP, e travar o IP derrubaria a equipe por causa de um
    funcionario desmemoriado.
    """
    b = cenario["brutus"].id
    _com_senha(b)
    from tenant.models import Barbeiro

    from app.services.senha import gerar

    Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=b,
        nome="Outro",
        whatsapp="11966665555",
        ativo=True,
        senha_hash=gerar(SENHA),
    )

    for _ in range(5):
        _logar(client, senha="chute")

    assert _logar(client, whatsapp="11966665555").status_code == 200


# --------------------------------------------------------- as tres do banco


def test_cookie_valido_de_OUTRA_barbearia_nao_vale_neste_host(client, cenario):
    """O pior bug possivel do multi-tenant, e o unico que a assinatura sozinha
    nao pega: o token e valido, o barbeiro existe, e mesmo assim e de outra
    barbearia. Sem a conferencia de `bid`, um dono logado abre o subdominio da
    concorrente e entra no painel dela com o proprio cookie.
    """
    _com_senha(cenario["brutus"].id)
    _com_senha(cenario["dontony"].id, senha="outra-senha-999")

    assert _logar(client).status_code == 200
    assert _eu(client, "brutus.localhost").status_code == 200
    assert _eu(client, "dontony.localhost").status_code == 401


def test_desativar_o_barbeiro_derruba_a_sessao_na_hora(client, cenario):
    from tenant.models import Barbeiro

    barbeiro = _com_senha(cenario["brutus"].id)
    _logar(client)
    assert _eu(client).status_code == 200

    Barbeiro.objects.using("owner").filter(id=barbeiro.id).update(ativo=False)
    assert _eu(client).status_code == 401


def test_bumpar_o_tokenVersion_derruba_a_sessao(client, cenario):
    """E o que torna "derrubar as sessoes" possivel sem existir lista de
    sessao nenhuma para varrer.
    """
    from tenant.models import Barbeiro

    barbeiro = _com_senha(cenario["brutus"].id)
    _logar(client)
    assert _eu(client).status_code == 200

    Barbeiro.objects.using("owner").filter(id=barbeiro.id).update(token_version=1)
    assert _eu(client).status_code == 401


def test_sem_cookie_o_eu_recusa(client, cenario):
    assert _eu(client).status_code == 401


def test_o_401_apaga_o_cookie(client, cenario):
    """Sessao morta que fica no navegador vira 401 em laco: a tela pede, leva
    401, vai para o login, e o login volta porque o cookie ainda esta la.
    """
    from app.services.sessao import COOKIE_SESSAO

    from tenant.models import Barbeiro

    barbeiro = _com_senha(cenario["brutus"].id)
    _logar(client)
    Barbeiro.objects.using("owner").filter(id=barbeiro.id).update(ativo=False)

    r = _eu(client)
    assert r.status_code == 401
    assert r.cookies[COOKIE_SESSAO].value == ""


def test_logout_apaga_o_cookie_e_funciona_sempre(client, cenario):
    """Sem sessao valida tambem: exigir sessao para poder sair criaria o beco
    em que um cookie corrompido nao pode ser descartado pelo botao de sair.
    """
    from app.services.sessao import COOKIE_SESSAO

    r = client.post(
        "/api/auth/logout",
        content_type="application/json",
        headers={"host": "brutus.localhost", **CABECALHO},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert r.cookies[COOKIE_SESSAO].value == ""


# --------------------------------------------------------- o crivo do painel


def test_o_crivo_do_painel_deixou_de_negar_tudo(client, cenario):
    """Ate a fatia 1 ele negava tudo de proposito, porque o criterio de
    verdade nao existia. Agora existe: com sessao valida o pedido ATRAVESSA o
    middleware — e cai em 404 porque nenhuma rota de painel foi escrita ainda,
    o que e a resposta certa. 404 aqui prova que o crivo deixou passar; 401
    provaria que ele continua cego.
    """
    _com_senha(cenario["brutus"].id)
    _logar(client)
    assert client.get("/api/painel/agenda", headers={"host": "brutus.localhost"}).status_code == 404


def test_o_crivo_do_painel_continua_negando_sem_sessao(client, cenario):
    r = client.get("/api/painel/agenda", headers={"host": "brutus.localhost"})
    assert r.status_code == 401


def test_o_crivo_do_painel_nega_cookie_de_outra_barbearia(client, cenario):
    """A protecao por POSICAO tem que valer a conferencia INTEIRA, nao so a
    assinatura: uma rota nova sob /api/painel nasce protegida sem ninguem
    decidir nada, e "protegida" precisa incluir o `bid`.
    """
    _com_senha(cenario["brutus"].id)
    _logar(client)
    r = client.get("/api/painel/agenda", headers={"host": "dontony.localhost"})
    assert r.status_code == 401


# ------------------------------------------------------------------ o convite


def _convidado(barbearia_id, token="token-de-teste", horas=48):
    from django.utils import timezone

    from app.services.senha import hash_de_convite
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome="Convidado",
        whatsapp="11955554444",
        ativo=True,
        papel="DONO",
        convite_token_hash=hash_de_convite(token),
        convite_expira_em=timezone.now() + timedelta(hours=horas),
    )


def _aceitar(client, token="token-de-teste", senha="senha-nova-123", host="brutus.localhost"):
    return client.post(
        f"/api/auth/convite/{token}",
        {"senha": senha},
        content_type="application/json",
        headers={"host": host, **CABECALHO},
    )


def test_convite_aceito_grava_a_senha_e_o_barbeiro_passa_a_logar(client, cenario):
    """Sem esta rota o painel de admin entrega contas que ninguem consegue
    usar: o dono nasce com senhaHash nulo, e nulo nao loga.
    """
    _convidado(cenario["brutus"].id)

    assert _aceitar(client).json() == {"ok": True}
    r = _logar(client, whatsapp="11955554444", senha="senha-nova-123")
    assert r.status_code == 200
    assert r.json()["papel"] == "DONO"


def test_o_convite_e_de_uso_unico(client, cenario):
    """O link viaja pelo WhatsApp. Se ele continuasse valendo, quem o tivesse
    poderia trocar a senha do barbeiro depois — inclusive com ele ja usando a
    conta.
    """
    _convidado(cenario["brutus"].id)
    assert _aceitar(client).status_code == 200
    assert _aceitar(client, senha="senha-outra-999").status_code == 404


def test_convite_vencido_da_404(client, cenario):
    _convidado(cenario["brutus"].id, horas=-1)
    assert _aceitar(client).status_code == 404


def test_token_inexistente_da_404_igual_ao_vencido(client, cenario):
    """Um desfecho so: distinguir "nao existe" de "venceu" diria a quem chuta
    tokens que ele acertou um dia.
    """
    _convidado(cenario["brutus"].id, horas=-1)
    vencido = _aceitar(client)
    inexistente = _aceitar(client, token="nao-existe")
    assert (vencido.status_code, vencido.json()) == (
        inexistente.status_code,
        inexistente.json(),
    )


def test_senha_curta_da_422_e_nao_grava(client, cenario):
    _convidado(cenario["brutus"].id)
    r = _aceitar(client, senha="curta")
    assert r.status_code == 422
    assert "8" in r.json()["erro"]
    # E o convite continua de pe: recusar a senha nao pode queimar o link.
    assert _aceitar(client).status_code == 200


def test_o_convite_de_uma_barbearia_nao_vale_no_host_da_outra(client, cenario):
    """O RLS e quem escopa a busca. Sem ele, o mesmo token aceito de qualquer
    subdominio trocaria a senha de um barbeiro de outra barbearia.
    """
    _convidado(cenario["brutus"].id)
    assert _aceitar(client, host="dontony.localhost").status_code == 404
    assert _aceitar(client, host="brutus.localhost").status_code == 200
