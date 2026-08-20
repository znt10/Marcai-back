import uuid

import pytest
from django.db import IntegrityError, transaction

from tenant.identidade import normalizar_login
from tenant.models import PapelUsuario, Usuario

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _criar(login, papel=PapelUsuario.BARBEIRO, barbearia_id=..., **extra):
    """Cria pelo alias `owner`, que a politica `owner_irrestrito` isenta do
    RLS — montar cenario atravessa tenants, e e para isso que ela existe."""
    return Usuario.objects.using("owner").create(
        id=uuid.uuid4(), login=login, papel=papel, barbearia_id=barbearia_id, **extra,
    )


# --------------------------------------------------------------------------
# `login` unico
# --------------------------------------------------------------------------

def test_login_repetido_e_recusado(cenario):
    b = cenario["brutus"].id
    _criar("11911112222", barbearia_id=b)

    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar("11911112222", barbearia_id=b)


def test_login_e_unico_no_sistema_inteiro_e_nao_por_barbearia(cenario):
    """O `unique` NAO e' por tenant, e essa e a diferenca que mais surpreende
    em relacao a `Barbeiro`, que permite o mesmo whatsapp em barbearias
    diferentes (`unique(barbearia, whatsapp)`).

    Tem de ser global: o login e digitado ANTES de existir sessao, e e ele que
    responde "quem esta entrando?". Se o mesmo valor existisse em duas
    barbearias, a resposta dependeria de um tenant que ainda nao foi resolvido.
    """
    _criar("11911112222", barbearia_id=cenario["brutus"].id)

    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar("11911112222", barbearia_id=cenario["dontony"].id)


# --------------------------------------------------------------------------
# A CheckConstraint: ADMIN nao tem barbearia, todo o resto tem
# --------------------------------------------------------------------------

def test_admin_nasce_sem_barbearia():
    admin = _criar("admin", papel=PapelUsuario.ADMIN, barbearia_id=None)
    assert admin.barbearia_id is None


def test_admin_com_barbearia_e_recusado(cenario):
    """Um ADMIN preso a uma barbearia seria escondido do proprio admin pelo
    RLS — ele so' alcanca a linha de `barbearia_id IS NULL`."""
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar("admin", papel=PapelUsuario.ADMIN, barbearia_id=cenario["brutus"].id)


@pytest.mark.parametrize("papel", [PapelUsuario.DONO, PapelUsuario.BARBEIRO])
def test_nao_admin_sem_barbearia_e_recusado(papel, cenario):
    """O espelho do caso acima, e o mais traicoeiro dos dois: um DONO com
    `barbearia_id` NULL nao casaria `tenant_isolation` (some para o runtime) e
    casaria `admin_da_plataforma` (aparece para o admin da plataforma). Vira
    um "usuario fantasma" — existe, ninguem certo enxerga.
    """
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar("alguem@x.com", papel=papel, barbearia_id=None)


# --------------------------------------------------------------------------
# Normalizacao pela FORMA — os dois casos que o card nomeia
# --------------------------------------------------------------------------

def test_email_colide_com_o_mesmo_email_torto(cenario):
    """`" Joao@X.com "` e `joao@x.com` sao a MESMA conta. Sem canonizar, o
    banco veria duas strings diferentes, o `unique` nao acusaria nada, e o dono
    erraria a senha sem ter errado a senha."""
    assert normalizar_login(" João@X.com ") == normalizar_login("joao@x.com")

    _criar(normalizar_login("joao@x.com"), barbearia_id=cenario["brutus"].id)
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar(normalizar_login(" João@X.com "), barbearia_id=cenario["brutus"].id)


def test_whatsapp_colide_com_o_mesmo_numero_torto(cenario):
    """`"(11) 99999-8888"` e `"11999998888"` sao o MESMO barbeiro. Cada
    tentativa com o numero "errado" ainda contaria para a trava de 5 —
    trancando para fora quem digitou certo."""
    assert normalizar_login("(11) 99999-8888") == normalizar_login("11999998888")

    _criar(normalizar_login("11999998888"), barbearia_id=cenario["brutus"].id)
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _criar(normalizar_login("(11) 99999-8888"), barbearia_id=cenario["brutus"].id)


def test_a_forma_decide_a_regra():
    """As tres formas caem em tres regras, e o `@` e conferido primeiro."""
    assert normalizar_login("  ADMIN  ") == "admin"          # usuario do admin
    assert normalizar_login("Dono@Barbearia.com") == "dono@barbearia.com"
    assert normalizar_login("+55 (11) 99999-8888") == "11999998888"


def test_login_vazio_ou_ausente_e_none():
    """None e o contrato, igual ao de `telefone.normalizar`: quem chama decide
    a mensagem. Uma string vazia gravada seria um login que ninguem digita e
    que mesmo assim ocupa o `unique`."""
    assert normalizar_login(None) is None
    assert normalizar_login("   ") is None


def test_numero_com_cara_de_telefone_que_nao_e_telefone_nao_vira_none():
    """`telefone.normalizar` recusa isto (nao tem 10-11 digitos nacionais), e a
    recusa NAO pode virar login nenhum: o valor cai na regra de usuario e
    continua existindo. Devolver None aqui transformaria "numero invalido" em
    "usuario sumiu", que e' erro reportado longe da causa."""
    assert normalizar_login("123") == "123"
