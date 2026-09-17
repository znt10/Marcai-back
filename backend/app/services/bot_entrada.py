"""A porta de entrada das mensagens de cliente no webhook.

`ler_mensagem` e' PURA e roda para TODO evento de mensagem. Num numero de uso
real, 40 de 42 eventos eram de grupo, quase todos com midia (spec, secao 11):
o descarte tem que acontecer antes de qualquer consulta ao banco.

O que passa vai para a fila com quatro campos, nao com o corpo inteiro: o
webhook responde em milissegundos, muito antes de a Evolution pensar em
reenviar, e a task fica testavel sem inventar um JSON da Evolution.
"""

from dataclasses import dataclass
from datetime import datetime

from tenant.models import EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia
from tenant.telefone import do_jid

from .bot import silenciar
from .whatsapp_instancias import barbearia_id_do_nome

EVENTO_MENSAGEM = "messages.upsert"


@dataclass(frozen=True)
class Recebida:
    barbearia_id: str
    numero: str
    texto: str | None
    mensagem_id: str
    do_proprio_numero: bool


def ler_mensagem(corpo) -> "Recebida | str":
    if not isinstance(corpo, dict):
        return "corpo"
    if str(corpo.get("event") or "").lower() != EVENTO_MENSAGEM:
        return "evento"
    nome = corpo.get("instance")
    barbearia_id = barbearia_id_do_nome(nome) if isinstance(nome, str) else None
    if barbearia_id is None:
        return "instancia"
    dados = corpo.get("data")
    chave = dados.get("key") if isinstance(dados, dict) else None
    if not isinstance(chave, dict):
        return "dados"
    jid = chave.get("remoteJid")
    if isinstance(jid, str) and jid.endswith("@g.us"):
        return "grupo"
    alt = chave.get("remoteJidAlt")
    if (
        isinstance(jid, str) and jid.endswith("@lid")
        and isinstance(alt, str) and alt.endswith("@s.whatsapp.net")
    ):
        # Chat endereçado por `@lid`: o numero de verdade vem em
        # `remoteJidAlt`. Vale para cliente e para `fromMe` — o dono
        # respondendo nesse chat ainda precisa calar o bot. Sem alt de
        # pessoa, `do_jid` devolve None e o evento e' descartado.
        jid = alt
    numero = do_jid(jid)
    if numero is None:
        return "numero"
    mensagem_id = chave.get("id")
    if not isinstance(mensagem_id, str) or not mensagem_id:
        return "id"
    mensagem = dados.get("message") if isinstance(dados.get("message"), dict) else {}
    texto = mensagem.get("conversation")
    if not isinstance(texto, str) or not texto.strip():
        # Resposta CITANDO outra mensagem — como quem responde o lembrete.
        citando = mensagem.get("extendedTextMessage")
        texto = citando.get("text") if isinstance(citando, dict) else None
    if not isinstance(texto, str) or not texto.strip():
        texto = None
    return Recebida(barbearia_id, numero, texto, mensagem_id, chave.get("fromMe") is True)


def receber(corpo, agora: datetime) -> str:
    lida = ler_mensagem(corpo)
    if isinstance(lida, str):
        return f"ignorado:{lida}"
    # Mensagem de CLIENTE sem texto (midia, figurinha, ...) sai antes de
    # qualquer consulta: nao ha nada a enfileirar de qualquer jeito, ligado ou
    # nao o bot. `fromMe` fica de fora desta conta — o dono respondendo com
    # audio ainda e' gente atendendo, e precisa seguir ate' `silenciar`.
    if not lida.do_proprio_numero and lida.texto is None:
        return "ignorado:sem_texto"
    with com_barbearia(lida.barbearia_id):
        instancia = WhatsappInstancia.objects.filter(barbearia_id=lida.barbearia_id).first()
    if (
        instancia is None
        or not instancia.bot_ativo
        or instancia.estado != EstadoInstancia.CONECTADO
    ):
        return "ignorado:desligado"
    if lida.do_proprio_numero:
        return silenciar(lida.barbearia_id, lida.numero, lida.mensagem_id, agora)
    enfileirar(lida)
    return "enfileirado"


def enfileirar(lida: Recebida) -> None:
    # Import tardio: `app.tasks` importa servicos, e este e' um deles.
    from app.tasks import tratar_mensagem

    tratar_mensagem.delay(lida.barbearia_id, lida.numero, lida.texto, lida.mensagem_id)
