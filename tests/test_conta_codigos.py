import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.conta_codigos import conferir_codigo, consumir_link, novo_codigo
from tenant.models import CodigoConta, ContaCliente, FinalidadeCodigo

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _conta(confirmada=True):
    return ContaCliente.objects.using("owner").create(
        id=str(uuid.uuid4()), nome="Ana", whatsapp="5511999990001", senha_hash="x",
        confirmada_em=T0 if confirmada else None,
    )


def test_codigo_tem_seis_digitos_e_guarda_so_o_hash():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR)
    assert len(codigo) == 6
    assert codigo.isdigit()
    guardado = CodigoConta.objects.get(conta_id=conta.id)
    assert guardado.hash != codigo
    assert codigo not in guardado.hash
    assert conferir_codigo(conta.id, codigo) is True


def test_codigo_novo_invalida_o_anterior():
    conta = _conta()
    primeiro = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR, agora=T0)
    segundo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR, agora=T0)
    # Os dois podem, por sorte, ser iguais (1 em 10^6): nesse caso o segundo e'
    # o valido e o teste de "primeiro nao confere" nao diz nada.
    if primeiro == segundo:
        pytest.skip("sorteio repetido")
    assert conferir_codigo(conta.id, primeiro, agora=T0) is False
    assert conferir_codigo(conta.id, segundo, agora=T0) is True


def test_codigo_vence_em_10_min():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR, agora=T0)
    assert conferir_codigo(conta.id, codigo, agora=T0 + timedelta(minutes=10, seconds=1)) is False


def test_codigo_ainda_vale_aos_9_min():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR, agora=T0)
    assert conferir_codigo(conta.id, codigo, agora=T0 + timedelta(minutes=9)) is True


def test_codigo_serve_uma_vez():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR)
    assert conferir_codigo(conta.id, codigo) is True
    assert conferir_codigo(conta.id, codigo) is False


def test_cinco_erros_queimam_o_codigo():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR)
    errado = "000000" if codigo != "000000" else "111111"
    for _ in range(5):
        assert conferir_codigo(conta.id, errado) is False
    assert conferir_codigo(conta.id, codigo) is False
    assert CodigoConta.objects.get(conta_id=conta.id).tentativas == 5


def test_codigo_de_outra_conta_nao_confere():
    a = _conta()
    b = ContaCliente.objects.using("owner").create(
        id=str(uuid.uuid4()), nome="Bia", whatsapp="5511999990002", senha_hash="x",
    )
    codigo = novo_codigo(a.id, FinalidadeCodigo.CONFIRMAR)
    assert conferir_codigo(b.id, codigo) is False


def test_conferir_sem_codigo_aberto_da_false():
    assert conferir_codigo(_conta().id, "123456") is False


def test_link_e_um_token_longo_e_guarda_so_o_hash():
    conta = _conta()
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    assert len(token) >= 32
    assert CodigoConta.objects.get(conta_id=conta.id).hash != token


def test_link_serve_uma_vez():
    conta = _conta()
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    achada = consumir_link(token)
    assert achada is not None and str(achada.id) == str(conta.id)
    assert consumir_link(token) is None


def test_link_vence_em_30_min():
    conta = _conta()
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA, agora=T0)
    assert consumir_link(token, agora=T0 + timedelta(minutes=30, seconds=1)) is None


def test_link_ainda_vale_aos_29_min():
    conta = _conta()
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA, agora=T0)
    assert consumir_link(token, agora=T0 + timedelta(minutes=29)) is not None


def test_link_de_conta_nao_confirmada_nao_serve():
    conta = _conta(confirmada=False)
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    assert consumir_link(token) is None


def test_link_novo_invalida_o_anterior():
    conta = _conta()
    antigo = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    novo = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    assert consumir_link(antigo) is None
    assert consumir_link(novo) is not None


def test_finalidades_nao_se_misturam():
    conta = _conta()
    codigo = novo_codigo(conta.id, FinalidadeCodigo.CONFIRMAR)
    token = novo_codigo(conta.id, FinalidadeCodigo.NOVA_SENHA)
    # Gerar o link nao queima o codigo de confirmar, e um token nao e' codigo.
    assert conferir_codigo(conta.id, codigo) is True
    assert consumir_link(token) is not None
    assert consumir_link(codigo) is None
