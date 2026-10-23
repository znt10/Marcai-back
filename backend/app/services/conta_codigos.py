import hmac
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from app.services.senha import hash_de_convite
from tenant.config import (
    CONTA_CODIGO_TENTATIVAS,
    CONTA_CODIGO_VALIDADE_MIN,
    CONTA_LINK_VALIDADE_MIN,
)
from tenant.models import CodigoConta, ContaCliente, FinalidadeCodigo

# Codigo de confirmacao (6 digitos) e link de senha nova, os dois guardados so'
# como hash em `CodigoConta` (tabela fora do RLS: le-se direto, sem
# `com_barbearia`). O valor em claro existe em UM lugar: o retorno de
# `novo_codigo`, para quem vai manda-lo pelo WhatsApp. Nenhuma resposta da API
# o devolve.
#
# `agora` e' parametro opcional so' para o teste mandar no relogio sem
# depender de freezegun; em producao ninguem o passa.


def _hash_do_codigo(conta_id, codigo: str) -> str:
    # Seis digitos sao so' 10^6 valores: sem o id da conta no hash, dois
    # codigos iguais de contas diferentes teriam o mesmo hash, e uma tabela
    # pronta de 10^6 SHA-256 desfaria qualquer um. Com o id junto, a tabela e'
    # por conta — e quem segura o chute continua sendo `tentativas` + validade.
    return hash_de_convite(f"{conta_id}:{codigo}")


def novo_codigo(conta_id, finalidade: str, *, agora=None) -> str:
    """Gera, guarda o hash e devolve o valor em claro. Os codigos ainda abertos
    da mesma conta e finalidade morrem aqui: pedir outro e' dizer que o
    anterior nao serve mais, e dois codigos vivos dobrariam o que um chute
    acerta."""
    agora = agora or timezone.now()
    if finalidade == FinalidadeCodigo.CONFIRMAR:
        # randbelow, nao random: o codigo e' segredo. Zero a esquerda preservado.
        valor = f"{secrets.randbelow(10**6):06d}"
        guardado = _hash_do_codigo(conta_id, valor)
        validade = timedelta(minutes=CONTA_CODIGO_VALIDADE_MIN)
    else:
        valor = secrets.token_urlsafe(32)
        guardado = hash_de_convite(valor)
        validade = timedelta(minutes=CONTA_LINK_VALIDADE_MIN)

    with transaction.atomic():
        CodigoConta.objects.filter(
            conta_id=conta_id, finalidade=finalidade, usado_em__isnull=True,
        ).update(usado_em=agora)
        CodigoConta.objects.create(
            conta_id=conta_id, finalidade=finalidade, hash=guardado,
            expira_em=agora + validade, criado_em=agora,
        )
    return valor


def conferir_codigo(conta_id, digitado: str, *, agora=None) -> bool:
    """Confere o codigo de CONFIRMAR e o consome se bater. Tudo sob
    `select_for_update`: dois pedidos simultaneos com o mesmo chute nao podem
    ler `tentativas` ao mesmo tempo e escapar do limite de cinco."""
    agora = agora or timezone.now()
    with transaction.atomic():
        codigo = (
            CodigoConta.objects.select_for_update()
            .filter(
                conta_id=conta_id, finalidade=FinalidadeCodigo.CONFIRMAR,
                usado_em__isnull=True,
            )
            .order_by("-criado_em")
            .first()
        )
        if (
            codigo is None
            or codigo.expira_em <= agora
            or codigo.tentativas >= CONTA_CODIGO_TENTATIVAS
        ):
            return False

        if not hmac.compare_digest(codigo.hash, _hash_do_codigo(conta_id, digitado.strip())):
            # F(): soma no banco, nao em cima do valor lido.
            CodigoConta.objects.filter(pk=codigo.pk).update(tentativas=F("tentativas") + 1)
            return False

        CodigoConta.objects.filter(pk=codigo.pk).update(usado_em=agora)
        return True


def consumir_link(token: str, *, agora=None) -> ContaCliente | None:
    """Troca o token do link pela conta, uma vez so'. None quando nao existe,
    ja foi usado, venceu ou a conta nao foi confirmada: conta que nunca provou
    o numero nao pode escolher senha por link, senao o link viraria um jeito de
    contornar o codigo."""
    agora = agora or timezone.now()
    with transaction.atomic():
        codigo = (
            CodigoConta.objects.select_for_update()
            .filter(hash=hash_de_convite(token), finalidade=FinalidadeCodigo.NOVA_SENHA)
            .first()
        )
        if codigo is None or codigo.usado_em is not None or codigo.expira_em <= agora:
            return None

        conta = ContaCliente.objects.get(pk=codigo.conta_id)
        if conta.confirmada_em is None:
            return None

        CodigoConta.objects.filter(pk=codigo.pk).update(usado_em=agora)
        return conta
