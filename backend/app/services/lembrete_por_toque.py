"""Lembrete por toque (spec 2026-11-03-lembrete-por-toque-design.md).

Pela Meta, cada mensagem que o Marcai manda por conta propria e' paga. O que
ela nao cobra: tudo o que vai a quem ESCREVEU para o numero nas 24 horas
seguintes. Entao o cliente toca em "Quero o lembrete no WhatsApp" na tela de
agendado, o WhatsApp abre com uma mensagem pronta (com o codigo) para o
numero central, e so' quem manda essa mensagem recebe a confirmacao (na
hora, de graca) e o lembrete de 1h antes. Quem escreveu tambem provou que o
numero e' dele, que tem internet e que nao bloqueou o Marcai.

O aceite vale para AQUELE agendamento (decisao do Jose): nao passa para os
proximos do mesmo cliente.

A chave e' `ligado()`: Meta ligada E `WHATSAPP_CENTRAL_NUMERO` preenchido.
Desligada, todo envio e' o de antes — o deploy do back e do front vem
primeiro, a variavel no Coolify depois.
"""

import logging
import os
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from tenant import telefone

from . import whatsapp_meta

logger = logging.getLogger(__name__)

# O alfabeto de `agendamentos._ALFABETO_CODIGO` (sem 0, 1, i, l, o), 10
# caracteres, sem letra ou digito colado dos dois lados. O cliente pode
# apagar o resto da mensagem, mandar em maiuscula ou colar no "Código:".
_CODIGO = re.compile(r"(?<![0-9a-z])[2-9a-hjkmnp-z]{10}(?![0-9a-z])")


def numero_central() -> str | None:
    """Os digitos nacionais do numero central (`83988982852`), ou None.

    Aceita o numero colado do WhatsApp Manager ("+55 83 8898-2852"): sem
    tirar o 55, o `wa.me` virava 5555… e o botao abria uma conversa que nao
    existe — com a chave ligada, ninguem recebia nada. Invalido desliga a
    chave e grita no log."""
    bruto = os.environ.get("WHATSAPP_CENTRAL_NUMERO", "").strip()
    if not bruto:
        return None
    nacional = telefone.normalizar(bruto)
    if nacional is None:
        logger.error(
            "[lembrete-por-toque] WHATSAPP_CENTRAL_NUMERO invalido (%r): chave desligada", bruto,
        )
    return nacional


def ligado() -> bool:
    return whatsapp_meta.ligado() and numero_central() is not None


def texto_pronto(barbearia_nome: str, codigo: str) -> str:
    """O mesmo texto do front (`src/lib/lembretePorToque.ts`). "em", e nao
    "na": o nome pode ser "Dom Tony" ou "Espaço Bela"."""
    return f"Quero o lembrete do meu horário em {barbearia_nome}. Código: {codigo}"


def link(barbearia_nome: str, codigo: str) -> str | None:
    central = numero_central()
    if central is None:
        return None
    return f"https://wa.me/55{central}?text={quote(texto_pronto(barbearia_nome, codigo))}"


# A janela da Meta e' de 24h desde a ultima mensagem do cliente; o toque e'
# uma. Com folga: texto fora da janela e' aceito com 200 e some depois.
JANELA_ABERTA = timedelta(hours=23)


def na_janela(pedido_em: datetime | None, agora: datetime) -> bool:
    """Se o toque (`lembrete_pedido_em`) ainda deixa mandar texto normal."""
    return pedido_em is not None and agora - pedido_em < JANELA_ABERTA


def codigos_no_texto(texto: str) -> list[str]:
    return list(dict.fromkeys(_CODIGO.findall((texto or "").lower())))


def registrar_pedido(texto: str, de_internacional: str, agora: datetime) -> str:
    """A mensagem que chegou ao central pelo webhook da Meta. Se ela traz o
    codigo de um agendamento CONFIRMADO e futuro, grava o pedido e responde
    com a confirmacao — de graca, porque o cliente acabou de escrever.

    Devolve "pedido" (gravou e respondeu), "repetido" (ja tinha pedido:
    responde de novo e nao regrava, nem troca o numero — a Meta reenvia
    webhook e o cliente aperta enviar duas vezes) ou "ignorado".

    O codigo e' unico no banco inteiro, mas `Agendamento` esta no RLS: o
    laco e' barbearia a barbearia, como no cron do lembrete.
    """
    # Import tardio: mensagens/whatsapp/convite puxam modelos e settings.
    from tenant.models import Agendamento, Barbearia, StatusAgendamento, TipoMensagem
    from tenant.rls import com_barbearia

    from .convite import link_do_agendamento
    from .mensagens import msg_confirmacao
    from .whatsapp import enviar_ao_cliente

    codigos = codigos_no_texto(texto)
    numero = telefone.canonico(de_internacional)
    if not codigos or numero is None:
        return "ignorado"

    for b in Barbearia.objects.filter(ativo=True):
        with com_barbearia(b.id):
            a = (
                Agendamento.objects.select_related("barbeiro", "cliente")
                .filter(codigo__in=codigos, status=StatusAgendamento.CONFIRMADO, inicio__gt=agora)
                .first()
            )
            if a is None:
                continue
            repetido = a.lembrete_pedido_em is not None
            # Todo toque, repetido ou nao, reabre a janela de 24h.
            Agendamento.objects.filter(id=a.id).update(lembrete_tocado_em=agora)
            if not repetido:
                # Condicional no UPDATE: dois webhooks iguais ao mesmo tempo
                # nao gravam duas vezes nem trocam o numero.
                gravou = Agendamento.objects.filter(
                    id=a.id, lembrete_pedido_em__isnull=True,
                ).update(lembrete_pedido_em=agora, lembrete_para=numero)
                repetido = gravou == 0

        # Responde a QUEM ESCREVEU (a janela de 24h aberta e' a dele), mesmo no
        # repetido de outro numero — sem trocar `lembrete_para`, que continua
        # sendo o primeiro. Responder ao primeiro deixava o segundo no vacuo
        # e deixava quem tem o link fazer o Marcai escrever ao cliente.
        enviar_ao_cliente(
            b, numero,
            msg_confirmacao(
                cliente_nome=a.cliente.nome, barbeiro_nome=a.barbeiro.nome,
                servico_nome=a.servico_nome, inicio=a.inicio, endereco=b.endereco,
                link=link_do_agendamento(b.slug, a.codigo),
                barbearia_nome=b.nome, contato=b.whatsapp_contato,
            ),
            tipo=TipoMensagem.CONFIRMACAO, cliente_nome=a.cliente.nome,
            # Ele acabou de escrever: texto normal, com as quebras de linha.
            na_janela=True,
        )
        return "repetido" if repetido else "pedido"

    return "ignorado"
