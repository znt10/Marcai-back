"""A maquina de conversa do bot de agendamento — PURA.

Sem banco, sem rede, sem relogio: tudo o que ela precisa chega por parametro,
e o que ela devolve e' uma DECISAO que a casca (`bot.py`) executa. Mesmo
desenho de `slots.py` e do `faixaDoWhatsapp` do front, e pelo mesmo motivo:
as regras que erram caro ("9 num menu de 3", "conversa de ontem", "0 em
qualquer lugar") ficam testaveis em milissegundos.

O que a deixa pura: o bot GUARDA as opcoes que ofereceu. Entender "2" e'
`opcoes[1]` — nao precisa perguntar nada ao banco. O banco so' entra para
MONTAR a proxima pergunta, e isso e' da casca.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from tenant.config import BOT_CONVERSA_EXPIRA_MIN, BOT_LEMBRETE_VALE_MIN

MENU = "MENU"
SERVICO = "SERVICO"
BARBEIRO = "BARBEIRO"
DIA = "DIA"
HORA = "HORA"
NOME = "NOME"
CONFIRMA = "CONFIRMA"
QUAL_AGENDAMENTO = "QUAL_AGENDAMENTO"
CONFIRMA_CANCEL = "CONFIRMA_CANCEL"
AGUARDANDO_LEMBRETE = "AGUARDANDO_LEMBRETE"

# Um servico so' ou um barbeiro so': perguntar "1 - Corte" e' fazer o cliente
# trabalhar para responder o obvio. DIA e HORA nunca pulam — um dia so' com
# vaga ainda e' uma escolha que a pessoa precisa ver.
PULA_SE_UNICA = frozenset({SERVICO, BARBEIRO})

# O numero SOZINHO, com no maximo uma pontuacao de quem digita rapido.
# Tres digitos nao casam: nenhuma lista do bot passa de dez itens, e "123"
# e' mais provavelmente um pedaço de telefone que uma escolha.
_NUMERO = re.compile(r"^\s*(\d{1,2})\s*[.)!]?\s*$")


@dataclass(frozen=True)
class Estado:
    passo: str
    opcoes: list
    rascunho: dict
    tentativas: int
    atualizado_em: datetime | None


@dataclass(frozen=True)
class Ir:
    """Avancar para `passo`. A casca busca as opcoes dele e pergunta."""

    passo: str
    rascunho: dict


@dataclass(frozen=True)
class Repetir:
    tentativas: int


@dataclass(frozen=True)
class ChamarHumano:
    pass


@dataclass(frozen=True)
class Marcar:
    rascunho: dict


@dataclass(frozen=True)
class Cancelar:
    codigo: str


@dataclass(frozen=True)
class ConfirmarLembrete:
    codigo: str


@dataclass(frozen=True)
class NaoVou:
    codigo: str


def numero_escolhido(texto) -> int | None:
    m = _NUMERO.match(texto) if isinstance(texto, str) else None
    return int(m.group(1)) if m else None


def expirou(estado: Estado, agora: datetime) -> bool:
    if estado.atualizado_em is None:
        return True
    limite = (
        BOT_LEMBRETE_VALE_MIN if estado.passo == AGUARDANDO_LEMBRETE
        else BOT_CONVERSA_EXPIRA_MIN
    )
    return agora - estado.atualizado_em > timedelta(minutes=limite)


def decidir(estado: Estado, texto, agora: datetime):
    """A ordem das regras e' o que importa, e cada uma tem um motivo:

    1. conversa velha recomeca ANTES de ler o numero — senao um "1" de ontem
       seria obedecido;
    2. o "0" vem antes de tudo o que sobrou, inclusive de "sem opcoes": e' a
       saida que as mensagens de beco mandam usar;
    3. NOME e' o unico passo de texto livre;
    4. sem opcoes guardadas nao ha o que entender, entao mostra o menu.
    """
    if expirou(estado, agora):
        return Ir(MENU, {})
    n = numero_escolhido(texto)
    if n == 0:
        return ChamarHumano()
    if estado.passo == NOME:
        nome = " ".join(texto.split()) if isinstance(texto, str) else ""
        if n is None and 2 <= len(nome) <= 60:
            return Ir(CONFIRMA, {**estado.rascunho, "cliente_nome": nome})
        return Repetir(estado.tentativas + 1)
    if not estado.opcoes:
        return Ir(MENU, {})
    if n is None or not 1 <= n <= len(estado.opcoes):
        return Repetir(estado.tentativas + 1)
    return _escolheu(estado.passo, estado.rascunho, estado.opcoes[n - 1]["id"])


def seguir_sozinho(passo: str, rascunho: dict, opcoes: list):
    if passo in PULA_SE_UNICA and len(opcoes) == 1:
        return _escolheu(passo, rascunho, opcoes[0]["id"])
    return None


def _apos(escolha: str, prefixo: str) -> str | None:
    return escolha[len(prefixo):] if escolha.startswith(prefixo) else None


def _escolheu(passo: str, r: dict, escolha: str):
    if passo == MENU:
        if escolha == "marcar":
            return Ir(SERVICO, {"cliente_nome": r.get("cliente_nome")})
        if escolha == "cancelar":
            return Ir(QUAL_AGENDAMENTO, {})
        codigo = _apos(escolha, "cancelar:")
        if codigo:
            return Ir(CONFIRMA_CANCEL, {"codigo": codigo})
    elif passo == SERVICO:
        return Ir(BARBEIRO, {**r, "servico_id": escolha})
    elif passo == BARBEIRO:
        return Ir(DIA, {**r, "barbeiro_id": escolha, "de": None})
    elif passo == DIA:
        de = _apos(escolha, "mais:")
        if de:
            return Ir(DIA, {**r, "de": de})
        return Ir(HORA, {**r, "dia": escolha, "depois": None})
    elif passo == HORA:
        if escolha == "outro_dia":
            return Ir(DIA, {**r, "de": None, "depois": None})
        depois = _apos(escolha, "depois:")
        if depois:
            return Ir(HORA, {**r, "depois": depois})
        inicio, barbeiro_id = escolha.split("|", 1)
        novo = {**r, "inicio": inicio, "barbeiro_escolhido": barbeiro_id}
        return Ir(CONFIRMA if r.get("cliente_nome") else NOME, novo)
    elif passo == CONFIRMA:
        if escolha == "confirmar":
            return Marcar(r)
    elif passo == QUAL_AGENDAMENTO:
        return Ir(CONFIRMA_CANCEL, {"codigo": escolha})
    elif passo == CONFIRMA_CANCEL:
        if escolha == "sim":
            return Cancelar(r["codigo"])
    elif passo == AGUARDANDO_LEMBRETE:
        codigo = _apos(escolha, "confirmar:")
        if codigo:
            return ConfirmarLembrete(codigo)
        codigo = _apos(escolha, "nao_vou:")
        if codigo:
            return NaoVou(codigo)
    # "recomecar", "nao" e qualquer id que nao se reconheca: volta ao menu.
    return Ir(MENU, {})
