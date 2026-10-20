import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from tenant.models import Cliente, ContaCliente

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _conta(whatsapp="5511999990001", nome="Ana"):
    return ContaCliente.objects.using("owner").create(
        id=str(uuid.uuid4()), nome=nome, whatsapp=whatsapp, senha_hash="x",
    )


def _cliente(barbearia, whatsapp):
    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome="Zé", whatsapp=whatsapp,
    )


def test_conta_fica_fora_do_rls():
    # A conta e' global: nao tem barbearia_id e nao ha politica nela. O runtime
    # a le sem `com_barbearia`.
    conta = _conta()
    achada = ContaCliente.objects.get(id=conta.id)
    assert achada.whatsapp == "5511999990001"
    assert achada.token_version == 0
    assert achada.confirmada_em is None


def test_whatsapp_da_conta_e_unico():
    _conta()
    with pytest.raises(IntegrityError):
        with transaction.atomic(using="owner"):
            _conta(nome="Outra")


def test_funcao_devolve_so_ids_das_barbearias_do_numero(cenario):
    _cliente(cenario["brutus"], "5511988887777")
    _cliente(cenario["dontony"], "5511977776666")
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM barbearias_do_whatsapp(%s)", [["5511988887777"]])
        linhas = cur.fetchall()
    assert {str(l[0]) for l in linhas} == {str(cenario["brutus"].id)}
    assert all(len(l) == 1 for l in linhas)


def test_funcao_junta_as_formas_e_nao_repete_barbearia(cenario):
    # Duas formas gravadas do mesmo numero na mesma barbearia: um id so'.
    _cliente(cenario["brutus"], "5511988887777")
    _cliente(cenario["brutus"], "11988887777")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM barbearias_do_whatsapp(%s)",
            [["5511988887777", "11988887777"]],
        )
        linhas = cur.fetchall()
    assert [str(l[0]) for l in linhas] == [str(cenario["brutus"].id)]


def test_runtime_continua_sem_ver_cliente_fora_do_tenant(cenario):
    _cliente(cenario["brutus"], "5511988887777")
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM barbearias_do_whatsapp(%s)", [["5511988887777"]])
        cur.fetchall()
    # A funcao nao abriu o RLS: a tabela segue invisivel fora do tenant.
    assert Cliente.objects.count() == 0
