import re
import uuid
from unittest.mock import patch

import pytest

from app.services import conta_limites, senha as senha_mod, trava_conta
from app.services.conta_codigos import novo_codigo
from tenant.config import CONTA_SESSAO_COOKIE
from tenant.models import CodigoConta, ContaCliente, FinalidadeCodigo
from tests.test_agendamentos import CABECALHO, HOST

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83982217869"
SENHA = "senha-boa-123"


@pytest.fixture(autouse=True)
def _segredo(monkeypatch):
    monkeypatch.setenv("SESSAO_JWT_SECRET", "segredo-so-de-teste")


@pytest.fixture
def envios():
    """Captura `(numero, texto)` de cada mensagem que sairia pelo central. O
    patch e' onde o servico IMPORTA a funcao, nao onde ela nasce."""
    saidas = []

    def captura(numero, texto):
        saidas.append((numero, texto))
        return True

    with patch("app.services.conta.enviar_pelo_central", side_effect=captura):
        yield saidas


def _post(client, caminho, corpo=None, host=HOST):
    return client.post(
        f"/api/conta/{caminho}", corpo or {},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )


def _eu(client, host=HOST):
    return client.get("/api/conta/eu", headers={"host": host})


def _codigo_de(envios):
    return re.search(r"\*(\d{6})\*", envios[-1][1]).group(1)


def _criar(client, whatsapp=NUMERO, nome="Ana", senha=SENHA):
    return _post(client, "criar", {"nome": nome, "whatsapp": whatsapp, "senha": senha})


def _conta_confirmada(client, envios, whatsapp=NUMERO, senha=SENHA):
    """Cria e confirma pelo caminho de verdade; devolve o cookie emitido."""
    assert _criar(client, whatsapp, senha=senha).status_code == 202
    r = _post(client, "confirmar", {"whatsapp": whatsapp, "codigo": _codigo_de(envios), "senha": SENHA})
    assert r.status_code == 200
    return r.cookies[CONTA_SESSAO_COOKIE].value


def _link_de(envios):
    return re.search(r"abre: (\S+)", envios[-1][1]).group(1)


# ----------------------------------------------------------------- criar


def test_criar_manda_codigo_e_a_resposta_nao_contem_o_codigo(client, cenario, envios):
    r = _criar(client)

    assert r.status_code == 202
    assert r.json() == {"ok": True}
    assert len(envios) == 1
    numero, texto = envios[0]
    # Sai em canonico (com o nono digito), nao como foi digitado.
    assert numero == NUMERO
    codigo = re.search(r"\*(\d{6})\*", texto).group(1)
    assert codigo.encode() not in r.content
    assert CONTA_SESSAO_COOKIE not in r.cookies
    # E a conta nasce pendente, com a senha so' em hash.
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    assert conta.confirmada_em is None
    assert conta.senha_hash != SENHA
    assert senha_mod.confere(conta.senha_hash, SENHA)


def test_criar_normaliza_numero_sem_nono_digito(client, cenario, envios):
    _criar(client, whatsapp="+55 83 8221-7869")
    assert envios[0][0] == NUMERO
    assert ContaCliente.objects.filter(whatsapp=NUMERO).count() == 1


@pytest.mark.parametrize("corpo", [
    {"nome": "A", "whatsapp": NUMERO, "senha": SENHA},
    {"nome": "Ana", "whatsapp": NUMERO, "senha": "12345"},
    {"nome": "Ana", "whatsapp": "123", "senha": SENHA},
    {"nome": "Ana", "whatsapp": NUMERO},
    {"nome": ["Ana"], "whatsapp": NUMERO, "senha": SENHA},
])
def test_criar_recusa_entrada_invalida_com_422(client, cenario, envios, corpo):
    r = _post(client, "criar", corpo)
    assert r.status_code == 422
    assert isinstance(r.json()["erro"], str)
    assert envios == []
    assert not ContaCliente.objects.exists()


def test_criar_com_numero_sem_whatsapp_422(client, cenario, envios):
    with patch("app.services.conta.numero_existe", return_value="nao_existe"):
        r = _criar(client)
    assert r.status_code == 422
    assert envios == []
    assert not ContaCliente.objects.exists()


def test_criar_com_conta_confirmada_409(client, cenario, envios):
    _conta_confirmada(client, envios)
    envios.clear()

    r = _criar(client, nome="Outra", senha="outra-senha-1")

    assert r.status_code == 409
    assert r.json() == {"erro": "Esse WhatsApp já tem conta. Entra com sua senha."}
    assert envios == []
    # A conta de verdade nao foi tocada.
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    assert conta.nome == "Ana"
    assert senha_mod.confere(conta.senha_hash, SENHA)


def test_criar_por_cima_de_conta_pendente_substitui(client, cenario, envios):
    _criar(client, nome="Ana", senha=SENHA)
    primeiro = _codigo_de(envios)

    r = _criar(client, nome="Ana Maria", senha="outra-senha-1")

    assert r.status_code == 202
    assert len(envios) == 2
    assert ContaCliente.objects.count() == 1
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    assert conta.nome == "Ana Maria"
    assert senha_mod.confere(conta.senha_hash, "outra-senha-1")
    assert not senha_mod.confere(conta.senha_hash, SENHA)
    # Um so' codigo vivo: o anterior morreu quando o novo nasceu.
    segundo = _codigo_de(envios)
    if primeiro != segundo:
        r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": primeiro, "senha": "outra-senha-1"})
        assert r.status_code == 400
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": segundo, "senha": "outra-senha-1"})
    assert r.status_code == 200


def test_criar_pelo_host_do_admin_404(client, cenario, envios):
    r = _criar_no(client, "admin.localhost")
    assert r.status_code == 404
    assert envios == []


def _criar_no(client, host):
    return _post(
        client, "criar", {"nome": "Ana", "whatsapp": NUMERO, "senha": SENHA}, host=host,
    )


def test_criar_sem_cabecalho_de_cliente_403(client, cenario, envios):
    r = client.post(
        "/api/conta/criar", {"nome": "Ana", "whatsapp": NUMERO, "senha": SENHA},
        content_type="application/json", headers={"host": HOST},
    )
    assert r.status_code == 403


def test_limite_de_envio_429(client, cenario, envios):
    for _ in range(3):
        assert _criar(client).status_code == 202

    r = _criar(client)

    assert r.status_code == 429
    assert r.json() == {"erro": "Muitos códigos pedidos. Tenta de novo mais tarde."}
    assert len(envios) == 3


def test_limite_de_envio_nao_troca_a_senha_da_pendente(client, cenario, envios):
    for _ in range(3):
        _criar(client)
    _criar(client, senha="senha-do-atacante")
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    assert senha_mod.confere(conta.senha_hash, SENHA)


def test_teto_geral_503(client, cenario, envios, monkeypatch):
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_DIA", 1)
    assert _criar(client, whatsapp="83982217869").status_code == 202

    r = _criar(client, whatsapp="83982217870")

    assert r.status_code == 503
    assert r.json() == {"erro": "Não conseguimos mandar o código agora. Tenta de novo mais tarde."}
    assert len(envios) == 1


def test_central_fora_503_e_devolve_a_vaga(client, cenario):
    with patch("app.services.conta.enviar_pelo_central", return_value=False):
        # Quatro vezes, mais que as 3 do limite por numero: se a vaga nao
        # voltasse, a quarta daria 429.
        respostas = [_criar(client).status_code for _ in range(4)]
    assert respostas == [503, 503, 503, 503]


def test_central_fora_responde_so_o_aviso(client, cenario):
    with patch("app.services.conta.enviar_pelo_central", return_value=False):
        r = _criar(client)
    assert r.status_code == 503
    assert r.json() == {"erro": "Não conseguimos mandar o código agora. Tenta de novo mais tarde."}


# ----------------------------------------------------------------- reenviar


def test_reenviar_manda_codigo_novo_para_a_pendente(client, cenario, envios):
    _criar(client)
    r = _post(client, "reenviar", {"whatsapp": "+55 83 98221-7869"})

    assert r.status_code == 202
    assert r.json() == {"ok": True}
    assert len(envios) == 2
    assert envios[1][0] == NUMERO
    codigo = _codigo_de(envios)
    assert codigo.encode() not in r.content
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": SENHA})
    assert r.status_code == 200


def test_reenviar_sem_conta_pendente_e_neutro(client, cenario, envios):
    sem_conta = _post(client, "reenviar", {"whatsapp": NUMERO})
    assert sem_conta.status_code == 202
    assert envios == []

    _conta_confirmada(client, envios, whatsapp="83982217870")
    envios.clear()
    confirmada = _post(client, "reenviar", {"whatsapp": "83982217870"})
    assert confirmada.status_code == 202
    assert envios == []
    assert sem_conta.json() == confirmada.json()


def test_reenviar_responde_429_igual_com_e_sem_pendente(client, cenario, envios):
    _criar(client, whatsapp="83982217870")
    for numero in ("83982217870", NUMERO):
        for _ in range(3):
            _post(client, "reenviar", {"whatsapp": numero})
    # `criar` ja gastou uma vaga do primeiro numero: os dois estouram no mesmo
    # ponto, tenha ou nao pendente.
    assert _post(client, "reenviar", {"whatsapp": "83982217870"}).status_code == 429
    assert _post(client, "reenviar", {"whatsapp": NUMERO}).status_code == 429


def test_reenviar_com_numero_invalido_422(client, cenario, envios):
    assert _post(client, "reenviar", {"whatsapp": "123"}).status_code == 422


# ----------------------------------------------------------------- confirmar


def test_confirmar_com_codigo_certo_loga(client, cenario, envios):
    _criar(client)
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": _codigo_de(envios), "senha": SENHA})

    assert r.status_code == 200
    assert r.json() == {"nome": "Ana", "whatsapp": "(83) 9 8221-7869"}
    assert CONTA_SESSAO_COOKIE in r.cookies
    assert _eu(client).status_code == 200
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    assert conta.confirmada_em is not None
    assert conta.token_version == 1


def test_confirmar_com_codigo_errado_400_e_nao_loga(client, cenario, envios):
    _criar(client)
    certo = _codigo_de(envios)
    errado = "000000" if certo != "000000" else "111111"

    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": errado, "senha": SENHA})

    assert r.status_code == 400
    assert r.json() == {"erro": "Código errado ou vencido."}
    assert CONTA_SESSAO_COOKIE not in r.cookies
    assert _eu(client).status_code == 401
    assert ContaCliente.objects.get(whatsapp=NUMERO).confirmada_em is None


@pytest.mark.parametrize("codigo", [None, ["123456"], {"a": 1}, True])
def test_confirmar_com_tipo_estranho_e_400_nao_500(client, cenario, envios, codigo):
    _criar(client)
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": SENHA})
    assert r.status_code == 400


def test_confirmar_sem_conta_400(client, cenario):
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": "123456", "senha": SENHA})
    assert r.status_code == 400
    assert r.json() == {"erro": "Código errado ou vencido."}


def test_confirmar_aceita_o_numero_em_outra_forma(client, cenario, envios):
    _criar(client)
    r = _post(
        client, "confirmar",
        {"whatsapp": "(83) 8221-7869", "codigo": _codigo_de(envios), "senha": SENHA},
    )
    assert r.status_code == 200


def test_confirmar_cinco_erros_queimam_o_codigo(client, cenario, envios):
    _criar(client)
    certo = _codigo_de(envios)
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):
        assert _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": errado, "senha": SENHA}).status_code == 400
    assert _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": certo, "senha": SENHA}).status_code == 400


def test_confirmar_conta_ja_confirmada_400(client, cenario, envios):
    _conta_confirmada(client, envios)
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": "123456", "senha": SENHA})
    assert r.status_code == 400


# ----------------------------------------------------------------- entrar


def test_entrar_com_senha_certa_loga(client, cenario, envios):
    _conta_confirmada(client, envios)
    client.cookies.clear()

    r = _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA})

    assert r.status_code == 200
    assert r.json() == {"nome": "Ana", "whatsapp": "(83) 9 8221-7869"}
    assert CONTA_SESSAO_COOKIE in r.cookies
    assert _eu(client).status_code == 200


def test_entrar_com_numero_em_outra_forma(client, cenario, envios):
    _conta_confirmada(client, envios, whatsapp="83982217869")
    client.cookies.clear()

    r = _post(client, "entrar", {"whatsapp": "+55 83 8221-7869", "senha": SENHA})

    assert r.status_code == 200


def test_entrar_em_conta_pendente_e_recusado(client, cenario, envios):
    _criar(client)
    r = _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA})
    assert r.status_code == 401
    assert r.json() == {"erro": "WhatsApp ou senha errados."}
    assert CONTA_SESSAO_COOKIE not in r.cookies


def test_entrar_com_conta_inexistente_ou_pendente_gasta_o_argon2(client, cenario, envios):
    """Sem isso a resposta generica e' teatro: o relogio contaria que a conta
    nao existe."""
    _criar(client, whatsapp="83982217870")
    chamadas = []
    original = senha_mod.confere

    def espiao(hash_guardado, senha):
        chamadas.append(hash_guardado)
        return original(hash_guardado, senha)

    with patch("app.services.conta.confere", side_effect=espiao):
        _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA})
        trava_conta.limpar(NUMERO)
        _post(client, "entrar", {"whatsapp": "83982217870", "senha": SENHA})
        _post(client, "entrar", {"whatsapp": "123", "senha": SENHA})

    assert len(chamadas) == 3
    assert chamadas[0] == senha_mod.hash_descartavel()


def test_entrar_senha_errada_401_e_trava_cresce(client, cenario, envios, monkeypatch):
    _conta_confirmada(client, envios)
    client.cookies.clear()
    agora = [1_000_000.0]
    monkeypatch.setattr(trava_conta, "_agora_ms", lambda: agora[0])

    r = _post(client, "entrar", {"whatsapp": NUMERO, "senha": "errada-errada"})
    assert r.status_code == 401
    primeira = trava_conta.espera_de(NUMERO)
    assert primeira > 0

    # Imediatamente depois, ate a senha CERTA toma a espera.
    assert _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA}).status_code == 429

    agora[0] += primeira + 1
    r = _post(client, "entrar", {"whatsapp": NUMERO, "senha": "errada-errada"})
    assert r.status_code == 401
    assert trava_conta.espera_de(NUMERO) > primeira


def test_entrar_travado_nao_roda_o_argon2(client, cenario, envios):
    _conta_confirmada(client, envios)
    client.cookies.clear()
    trava_conta.registrar_falha(NUMERO)
    with patch("app.services.conta.confere") as confere:
        r = _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA})
    assert r.status_code == 429
    confere.assert_not_called()


def test_entrar_certo_zera_a_trava(client, cenario, envios, monkeypatch):
    _conta_confirmada(client, envios)
    client.cookies.clear()
    agora = [1_000_000.0]
    monkeypatch.setattr(trava_conta, "_agora_ms", lambda: agora[0])
    _post(client, "entrar", {"whatsapp": NUMERO, "senha": "errada-errada"})
    agora[0] += 5_000

    assert _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA}).status_code == 200
    assert trava_conta.espera_de(NUMERO) == 0


def test_entrar_com_corpo_malformado_401(client, cenario):
    r = _post(client, "entrar", {"whatsapp": None, "senha": ["x"]})
    assert r.status_code == 401
    assert r.json() == {"erro": "WhatsApp ou senha errados."}


# ----------------------------------------------------------------- sair, eu


def test_sair_apaga_cookie(client, cenario, envios):
    _conta_confirmada(client, envios)

    r = _post(client, "sair")

    assert r.status_code == 200
    morto = r.cookies[CONTA_SESSAO_COOKIE]
    assert morto.value == ""
    assert morto["max-age"] == 0


def test_sair_funciona_sem_sessao_e_no_host_do_admin(client, cenario):
    assert _post(client, "sair").status_code == 200
    assert _post(client, "sair", host="admin.localhost").status_code == 200


def test_eu_sem_cookie_401(client, cenario):
    r = _eu(client)
    assert r.status_code == 401


def test_eu_devolve_nome_e_whatsapp_formatado(client, cenario, envios):
    _conta_confirmada(client, envios)
    r = _eu(client)
    assert r.status_code == 200
    assert r.json() == {"nome": "Ana", "whatsapp": "(83) 9 8221-7869"}


def test_eu_com_conta_pendente_401(client, cenario, envios):
    """Um cookie so' nasce depois da confirmacao, mas a peneira fina e' que
    garante: forja-lo para uma conta pendente nao abre nada."""
    from app.services import conta_sessao

    _criar(client)
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    client.cookies[CONTA_SESSAO_COOKIE] = conta_sessao.emitir(conta.id, conta.token_version)
    assert _eu(client).status_code == 401


# ----------------------------------------------------------------- esqueci


def test_esqueci_responde_igual_com_e_sem_conta(client, cenario, envios):
    _conta_confirmada(client, envios, whatsapp="83982217870")
    envios.clear()

    sem = _post(client, "esqueci", {"whatsapp": NUMERO})
    assert envios == []
    com = _post(client, "esqueci", {"whatsapp": "83982217870"})

    assert sem.status_code == com.status_code == 202
    assert sem.json() == com.json() == {"ok": True}
    # So' com conta confirmada sai mensagem.
    assert len(envios) == 1
    assert envios[0][0] == "83982217870"


def test_esqueci_nao_manda_link_para_conta_pendente(client, cenario, envios):
    _criar(client)
    envios.clear()
    r = _post(client, "esqueci", {"whatsapp": NUMERO})
    assert r.status_code == 202
    assert envios == []


def test_esqueci_manda_link_do_estabelecimento_de_onde_veio(client, cenario, envios, monkeypatch):
    monkeypatch.setenv("URL_BASE", "http://localhost:3000")
    _conta_confirmada(client, envios)
    envios.clear()

    r = _post(client, "esqueci", {"whatsapp": NUMERO}, host="dontony.localhost")

    link = _link_de(envios)
    assert link.startswith("http://dontony.localhost:3000/conta/nova-senha/")
    token = link.rsplit("/", 1)[1]
    assert token.encode() not in r.content


def test_esqueci_estoura_o_mesmo_limite_com_e_sem_conta(client, cenario, envios):
    _conta_confirmada(client, envios, whatsapp="83982217870")
    for numero in ("83982217870", NUMERO):
        # `_conta_confirmada` ja gastou 1 vaga do primeiro: 2 pedidos nele, 3
        # no outro, e o seguinte estoura os dois do mesmo jeito.
        for _ in range(2 if numero == "83982217870" else 3):
            assert _post(client, "esqueci", {"whatsapp": numero}).status_code == 202
        assert _post(client, "esqueci", {"whatsapp": numero}).status_code == 429


def test_esqueci_com_central_fora_503(client, cenario, envios):
    _conta_confirmada(client, envios)
    with patch("app.services.conta.enviar_pelo_central", return_value=False):
        r = _post(client, "esqueci", {"whatsapp": NUMERO})
    assert r.status_code == 503


# ----------------------------------------------------------------- nova senha


def _pedir_link(client, envios, host=HOST):
    _post(client, "esqueci", {"whatsapp": NUMERO}, host=host)
    return _link_de(envios).rsplit("/", 1)[1]


def test_link_de_nova_senha_serve_uma_vez(client, cenario, envios):
    _conta_confirmada(client, envios)
    client.cookies.clear()
    token = _pedir_link(client, envios)

    r = _post(client, f"nova-senha/{token}", {"senha": "senha-nova-77"})

    assert r.status_code == 200
    assert r.json() == {"nome": "Ana", "whatsapp": "(83) 9 8221-7869"}
    assert CONTA_SESSAO_COOKIE in r.cookies
    assert _eu(client).status_code == 200

    segunda = _post(client, f"nova-senha/{token}", {"senha": "outra-senha-88"})
    assert segunda.status_code == 404
    assert segunda.json() == {"erro": "Link inválido ou vencido."}
    # A senha nova e' a que vale, a antiga nao.
    client.cookies.clear()
    assert _post(client, "entrar", {"whatsapp": NUMERO, "senha": "senha-nova-77"}).status_code == 200
    trava_conta.limpar(NUMERO)
    assert _post(client, "entrar", {"whatsapp": NUMERO, "senha": SENHA}).status_code == 401


def test_nova_senha_derruba_sessao_antiga(client, cenario, envios):
    velho = _conta_confirmada(client, envios)
    assert _eu(client).status_code == 200
    token = _pedir_link(client, envios)

    assert _post(client, f"nova-senha/{token}", {"senha": "senha-nova-77"}).status_code == 200

    client.cookies[CONTA_SESSAO_COOKIE] = velho
    assert _eu(client).status_code == 401


def test_senha_curta_no_link_da_422_e_nao_queima_o_link(client, cenario, envios):
    _conta_confirmada(client, envios)
    token = _pedir_link(client, envios)

    curta = _post(client, f"nova-senha/{token}", {"senha": "123"})
    assert curta.status_code == 422
    assert CONTA_SESSAO_COOKIE not in curta.cookies

    assert _post(client, f"nova-senha/{token}", {"senha": "senha-nova-77"}).status_code == 200


def test_link_inexistente_404(client, cenario):
    r = _post(client, "nova-senha/nao-existe", {"senha": "senha-nova-77"})
    assert r.status_code == 404
    assert r.json() == {"erro": "Link inválido ou vencido."}


def test_link_de_conta_pendente_404(client, cenario, envios):
    _criar(client)
    conta = ContaCliente.objects.get(whatsapp=NUMERO)
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)

    assert _post(client, f"nova-senha/{token}", {"senha": "senha-nova-77"}).status_code == 404
    # E nada mudou na conta.
    conta.refresh_from_db()
    assert conta.confirmada_em is None
    assert senha_mod.confere(conta.senha_hash, SENHA)


def test_nova_senha_zera_a_trava_do_numero(client, cenario, envios):
    _conta_confirmada(client, envios)
    token = _pedir_link(client, envios)
    trava_conta.registrar_falha(NUMERO)
    assert trava_conta.espera_de(NUMERO) > 0

    _post(client, f"nova-senha/{token}", {"senha": "senha-nova-77"})

    assert trava_conta.espera_de(NUMERO) == 0


def test_o_link_nunca_fica_guardado_em_claro(client, cenario, envios):
    _conta_confirmada(client, envios)
    token = _pedir_link(client, envios)
    for c in CodigoConta.objects.all():
        assert token not in c.hash
        assert c.hash != token


# ----------------------------------------------------------- correcoes da revisao


def test_sequestro_de_cadastro_pendente_nao_funciona(client, cenario, envios):
    _criar(client, nome="Vitima", senha="senha-da-vitima")
    # O atacante pede por cima, com a senha dele; o codigo novo vai para a vitima.
    _criar(client, nome="Ataque", senha="senha-do-atacante")
    codigo = _codigo_de(envios)

    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": "senha-da-vitima"})

    assert r.status_code == 400
    assert r.json() == {"erro": "Código errado ou vencido."}
    assert CONTA_SESSAO_COOKIE not in r.cookies
    assert ContaCliente.objects.get(whatsapp=NUMERO).confirmada_em is None
    # Nenhum dos dois entra: a conta segue pendente.
    for senha in ("senha-da-vitima", "senha-do-atacante"):
        assert _post(client, "entrar", {"whatsapp": NUMERO, "senha": senha}).status_code == 401
        trava_conta.limpar(NUMERO)


def test_confirmar_com_a_senha_errada_conta_como_tentativa_e_nao_gasta_o_codigo(client, cenario, envios):
    _criar(client)
    codigo = _codigo_de(envios)
    for _ in range(5):
        r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": "errada-errada"})
        assert r.status_code == 400
    # Cinco tentativas gastas: nem o conjunto certo confirma mais.
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": SENHA})
    assert r.status_code == 400


def test_confirmar_com_a_senha_errada_nao_gasta_o_codigo_uma_vez(client, cenario, envios):
    _criar(client)
    codigo = _codigo_de(envios)
    assert _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": "errada-errada"}).status_code == 400
    assert _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": codigo, "senha": SENHA}).status_code == 200


def test_confirmar_sem_senha_400(client, cenario, envios):
    _criar(client)
    r = _post(client, "confirmar", {"whatsapp": NUMERO, "codigo": _codigo_de(envios)})
    assert r.status_code == 400
    assert r.json() == {"erro": "Código errado ou vencido."}


def test_erro_depois_da_reserva_devolve_a_vaga(client, cenario, envios):
    with patch("app.services.conta.novo_codigo", side_effect=RuntimeError("banco")):
        with pytest.raises(RuntimeError):
            client.raise_request_exception = True
            _criar(client)
    client.raise_request_exception = True
    # Se a vaga ficasse presa, tres falhas esgotariam o limite do numero.
    for _ in range(3):
        with patch("app.services.conta.novo_codigo", side_effect=RuntimeError("banco")):
            with pytest.raises(RuntimeError):
                _criar(client)
    assert _criar(client).status_code == 202


def test_conta_tem_balde_de_limite_proprio(client, cenario):
    from rest_framework.settings import api_settings

    assert api_settings.DEFAULT_THROTTLE_RATES["conta"] == "10/min"
    for _ in range(10):
        _post(client, "entrar", {"whatsapp": "123", "senha": "x"})
    assert _post(client, "entrar", {"whatsapp": "123", "senha": "x"}).status_code == 429
    # O login do painel segue livre.
    r = client.post(
        "/api/auth/login", {"whatsapp": "11988887777", "senha": "x"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 401
