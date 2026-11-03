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

import os
import re
from urllib.parse import quote

from . import whatsapp_meta

# O alfabeto de `agendamentos._ALFABETO_CODIGO` (sem 0, 1, i, l, o), 10
# caracteres, sem letra ou digito colado dos dois lados. O cliente pode
# apagar o resto da mensagem, mandar em maiuscula ou colar no "Código:".
_CODIGO = re.compile(r"(?<![0-9a-z])[2-9a-hjkmnp-z]{10}(?![0-9a-z])")


def numero_central() -> str | None:
    """Os digitos nacionais do numero central (`83988982852`), ou None."""
    digitos = re.sub(r"\D", "", os.environ.get("WHATSAPP_CENTRAL_NUMERO", ""))
    return digitos or None


def ligado() -> bool:
    return whatsapp_meta.ligado() and numero_central() is not None


def texto_pronto(barbearia_nome: str, codigo: str) -> str:
    """O mesmo texto do front (`src/lib/lembrete.ts`)."""
    return f"Quero o lembrete do meu horário na {barbearia_nome}. Código: {codigo}"


def link(barbearia_nome: str, codigo: str) -> str | None:
    central = numero_central()
    if central is None:
        return None
    return f"https://wa.me/55{central}?text={quote(texto_pronto(barbearia_nome, codigo))}"


def codigos_no_texto(texto: str) -> list[str]:
    return list(dict.fromkeys(_CODIGO.findall((texto or "").lower())))
