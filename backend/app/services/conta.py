from django.db import transaction
from django.db.models import F
from django.utils import timezone

from app.services import trava_conta
from app.services.conta_codigos import conferir_codigo, consumir_link, novo_codigo
from app.services.conta_limites import devolver_envio, devolver_teto, reservar_envio
from app.services.convite import link_da_vitrine
from app.services.mensagens import msg_codigo_conta, msg_link_nova_senha
from app.services.senha import confere, gerar, hash_descartavel
from app.services.whatsapp import enviar_pelo_central, numero_existe
from tenant.models import ContaCliente, FinalidadeCodigo
from tenant.telefone import canonico, normalizar

# A conta do cliente (spec 2026-10-20): o que cada rota HTTP decide, sem HTTP.
# As views so' traduzem o desfecho em status.
#
# O numero entra aqui em qualquer forma que a pessoa digite e sai `canonico()`
# ANTES de tocar limite, trava, busca ou gravacao: "+55 83 8221-7869" e
# "83982217869" sao o mesmo aparelho, e uma chave de limite por forma digitada
# daria tres vagas ao mesmo numero.

# Desfechos. Strings, e nao excecoes: sao fluxo normal, e o teste le melhor.
ENVIADO = "enviado"
NUMERO_INVALIDO = "numero_invalido"
SEM_WHATSAPP = "sem_whatsapp"
JA_TEM_CONTA = "ja_tem_conta"
LIMITE = "limite"
FORA = "fora"
OK = "ok"
TRAVADO = "travado"
INVALIDO = "invalido"


def _numero(bruto) -> str | None:
    """Digitado -> canonico, ou None. O `normalizar` valida o formato e o
    `canonico` poe o nono digito."""
    normal = normalizar(bruto)
    return canonico(normal) if normal else None


def _reservar(whatsapp: str, ip: str) -> str | None:
    """`reservar_envio` traduzido: numero/ip viram LIMITE (429) e o teto geral
    vira FORA (503: nao e' culpa de quem pediu, e o chip central esta poupado)."""
    motivo = reservar_envio(whatsapp, ip)
    if motivo is None:
        return None
    return FORA if motivo == "teto" else LIMITE


def _mandar(conta: ContaCliente, ip: str, finalidade: str, texto_de) -> str:
    """Gera o codigo/token, manda pelo central e, se nao saiu, devolve a vaga
    que o chamador reservou. O valor em claro nasce e morre aqui dentro."""
    valor = novo_codigo(conta.id, finalidade)
    if not enviar_pelo_central(conta.whatsapp, texto_de(valor)):
        devolver_envio(conta.whatsapp, ip)
        return FORA
    return ENVIADO


def criar(barbearia, ip: str, nome: str, whatsapp: str, senha: str) -> str:
    """Cria a conta PENDENTE e manda o codigo. Conta pendente de antes e'
    sobrescrita (nome e senha): quem nunca confirmou nao tem nada a perder, e
    o contrario trancaria o numero de quem errou a digitacao."""
    numero = _numero(whatsapp)
    if numero is None:
        return NUMERO_INVALIDO

    existente = ContaCliente.objects.filter(whatsapp=numero).first()
    if existente is not None and existente.confirmada_em is not None:
        return JA_TEM_CONTA

    # O oraculo de "esse numero tem WhatsApp" vem ANTES de gastar vaga: um
    # numero sem WhatsApp nao recebe nada, entao nao ha o que contar.
    if numero_existe(barbearia, numero, ip) == "nao_existe":
        return SEM_WHATSAPP

    recusa = _reservar(numero, ip)
    if recusa:
        return recusa

    try:
        return _gravar_e_mandar(numero, ip, nome, senha)
    except BaseException:
        # A vaga ja foi gasta: erro de banco ou do envio nao pode deixa-la presa.
        devolver_envio(numero, ip)
        raise


def _gravar_e_mandar(numero: str, ip: str, nome: str, senha: str) -> str:
    hash_da_senha = gerar(senha)
    with transaction.atomic():
        # `get_or_create` ja resolve a corrida de dois `criar` simultaneos (o
        # unique de `whatsapp` perde um insert e ele relê); o `select_for_update`
        # segura a linha ate o fim, para a troca de nome e senha nao se cruzar.
        conta, criada = ContaCliente.objects.select_for_update().get_or_create(
            whatsapp=numero, defaults={"nome": nome, "senha_hash": hash_da_senha},
        )
        if not criada:
            if conta.confirmada_em is not None:
                devolver_envio(numero, ip)
                return JA_TEM_CONTA
            conta.nome, conta.senha_hash = nome, hash_da_senha
            conta.save(update_fields=["nome", "senha_hash"])

    return _mandar(conta, ip, FinalidadeCodigo.CONFIRMAR, msg_codigo_conta)


def reenviar(ip: str, whatsapp: str) -> str:
    """Outro codigo para a conta pendente. Para numero sem conta pendente a
    resposta e' a MESMA (ENVIADO, sem mandar nada) e a vaga continua gasta: se
    a recusa por limite so' viesse quando ha pendente, o 429 contaria quais
    numeros estao no meio de um cadastro."""
    numero = _numero(whatsapp)
    if numero is None:
        return NUMERO_INVALIDO

    recusa = _reservar(numero, ip)
    if recusa:
        return recusa

    try:
        conta = ContaCliente.objects.filter(whatsapp=numero, confirmada_em__isnull=True).first()
        if conta is None:
            # Nada saiu: o numero e o IP seguem gastos (anti-enumeracao), mas o
            # teto geral do central nao.
            devolver_teto()
            return ENVIADO
        return _mandar(conta, ip, FinalidadeCodigo.CONFIRMAR, msg_codigo_conta)
    except BaseException:
        devolver_envio(numero, ip)
        raise


def confirmar(whatsapp: str, codigo: str, senha: str) -> ContaCliente | None:
    """Confere senha E codigo e confirma a conta. A senha e' conferida contra a
    da conta pendente: `criar` sobre pendente troca a senha, e sem esta
    conferencia quem a trocou faria a vitima confirmar a conta COM A SENHA DO
    ATACANTE ao digitar o codigo que recebeu. A senha vem ANTES do codigo e uma
    senha errada conta como codigo errado (gasta uma das 5 tentativas, sem
    consumir o codigo): so' quem sabe a senha chega a testar codigo, e quem
    nao sabe nao ganha chute livre na senha. Mesmo 400 para tudo.

    `token_version` sobe para que nada emitido antes valha depois."""
    numero = _numero(whatsapp)
    conta = (
        ContaCliente.objects.filter(whatsapp=numero, confirmada_em__isnull=True).first()
        if numero else None
    )
    if conta is None:
        confere(hash_descartavel(), senha)  # mesmo tempo de resposta
        return None

    with transaction.atomic():
        if not confere(conta.senha_hash, senha):
            # Um valor que nunca bate: so' queima uma tentativa do codigo vivo.
            conferir_codigo(conta.id, "")
            return None
        if not conferir_codigo(conta.id, codigo):
            return None
        ContaCliente.objects.filter(pk=conta.pk).update(
            confirmada_em=timezone.now(), token_version=F("token_version") + 1,
        )
    conta.refresh_from_db()
    return conta


def entrar(whatsapp: str, senha: str) -> tuple[str, ContaCliente | None]:
    """WhatsApp + senha. A espera da trava vem ANTES do argon2 (que e' caro de
    proposito), e toda recusa roda UM argon2: conta inexistente, pendente e
    numero malformado gastam o mesmo tempo da senha errada, senao o relogio
    contaria quem tem conta.

    A falha tambem e' registrada quando a conta nao existe, pelo mesmo motivo:
    uma espera que so' aparecesse para numero com conta seria o oraculo."""
    numero = _numero(whatsapp)
    if numero is None:
        confere(hash_descartavel(), senha)
        return INVALIDO, None

    if trava_conta.espera_de(numero) > 0:
        return TRAVADO, None

    conta = ContaCliente.objects.filter(whatsapp=numero).first()
    if conta is None or conta.confirmada_em is None:
        confere(hash_descartavel(), senha)
        trava_conta.registrar_falha(numero)
        return INVALIDO, None

    if not confere(conta.senha_hash, senha):
        trava_conta.registrar_falha(numero)
        return INVALIDO, None

    trava_conta.limpar(numero)
    return OK, conta


def esqueci(barbearia, ip: str, whatsapp: str) -> str:
    """Manda o link de senha nova SE houver conta confirmada. A resposta e' a
    mesma com e sem conta (ver `reenviar` sobre a vaga). O link abre no
    estabelecimento de onde o pedido veio."""
    numero = _numero(whatsapp)
    if numero is None:
        return NUMERO_INVALIDO

    recusa = _reservar(numero, ip)
    if recusa:
        return recusa

    try:
        conta = ContaCliente.objects.filter(whatsapp=numero, confirmada_em__isnull=False).first()
        if conta is None:
            # Nada saiu: o numero e o IP seguem gastos (anti-enumeracao), mas o
            # teto geral do central nao.
            devolver_teto()
            return ENVIADO
        base = f"{link_da_vitrine(barbearia.slug)}/conta/nova-senha/"
        return _mandar(
            conta, ip, FinalidadeCodigo.NOVA_SENHA, lambda token: msg_link_nova_senha(base + token),
        )
    except BaseException:
        devolver_envio(numero, ip)
        raise


def nova_senha(token: str, senha: str) -> ContaCliente | None:
    """Troca a senha pelo link. Consumir o link, gravar a senha e subir o
    `token_version` (que derruba as outras sessoes) ou acontecem juntos ou
    nenhum: se a gravacao falhar, o link nao pode ter sido gasto. O tamanho da
    senha ja foi conferido pela view, ANTES de chegar aqui, para que uma senha
    curta nao queime o link."""
    with transaction.atomic():
        conta = consumir_link(token)
        if conta is None:
            return None
        ContaCliente.objects.filter(pk=conta.pk).update(
            senha_hash=gerar(senha), token_version=F("token_version") + 1,
        )
    conta.refresh_from_db()
    trava_conta.limpar(conta.whatsapp)
    return conta
