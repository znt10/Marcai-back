import logging
import os
import time
import uuid
from dataclasses import dataclass

import requests

from tenant.config import (
    CHECK_NUMERO_LIMITE_POR_IP_HORA,
    CHECK_NUMERO_TIMEOUT_MS,
    CHECK_NUMERO_TTL_MS,
)
from tenant.models import MensagemNaoEnviada, PlanoBarbearia
from tenant.rls import com_barbearia

logger = logging.getLogger(__name__)

_HORA_MS = 3_600_000
_cache_numero: dict[str, dict] = {}
_uso_por_ip: dict[str, dict] = {}


def _agora_ms() -> float:
    return time.time() * 1000


def limpar_caches_numero() -> None:
    """So para teste — porte do `_limparCaches` do whatsapp.ts."""
    _cache_numero.clear()
    _uso_por_ip.clear()


def _config() -> dict[str, str]:
    """Lida a cada chamada, nao no topo do modulo: o teste troca as variaveis
    entre casos, e uma constante de modulo congelaria o primeiro valor —
    mesma razao do `config()` de whatsapp.ts.
    """
    return {
        "url": os.environ.get("EVOLUTION_API_URL", ""),
        "instancia": os.environ.get("EVOLUTION_INSTANCE", ""),
        "chave": os.environ.get("EVOLUTION_API_KEY", ""),
    }


@dataclass(frozen=True)
class Aceita:
    """A mensagem que a Evolution ACEITOU. `id` e `jid` sao o que permite
    apagar depois (a lista do dia). Podem vir None: aceita sem `key` ainda
    e' aceita — o destinatario recebe, so' nao da para apagar."""

    id: str | None
    jid: str | None


def enviar_a_equipe(whatsapp_digitos: str, mensagem: str) -> None:
    """Manda pela instancia CENTRAL do Marcai — barbeiro, dono, convite. Quem
    conhece a barbearia chama `enviar_a_equipe_da`, que so' cai aqui quando a
    barbearia nao tem aparelho conectado.

    O par disto e `enviar_ao_cliente`, e a diferenca nao e de estilo: **o
    numero central nunca fala com cliente.** Se falasse, um bloqueio do
    WhatsApp provocado por UMA barbearia derrubaria todas de uma vez — que e
    exatamente o risco que a instancia por barbearia existe para isolar. O
    central fala com um punhado de barbeiros que pediram para receber; e um
    perfil de uso completamente diferente.

    Vale nos DOIS planos. A barbearia sem zap nao deixa de avisar a equipe —
    ela so nao fala com o cliente.
    """
    _enviar(_config()["instancia"], whatsapp_digitos, mensagem)


def enviar_a_equipe_da(barbearia_id, whatsapp_digitos: str, mensagem: str) -> None:
    """O aviso de equipe de UMA barbearia: lista, novo horario, cancelamento,
    convite.

    Desde a etapa 1 do numero central (spec 2026-10-06) sai SEMPRE pelo
    central: o numero da barbearia nao fica mais ligado a Evolution. A
    assinatura com `barbearia_id` fica para nao mexer em quem chama.
    """
    enviar_a_equipe(whatsapp_digitos, mensagem)


def enviar_a_equipe_aceita(whatsapp_digitos: str, mensagem: str) -> Aceita | None:
    """`enviar_a_equipe` para quem precisa do que a Evolution devolveu — a
    lista do dia guarda o id e o jid para poder apaga-la depois."""
    return _enviar_aceita(_config()["instancia"], whatsapp_digitos, mensagem)


def enviar_ao_cliente(
    barbearia, whatsapp_digitos: str, mensagem: str, *, tipo: str, cliente_nome: str,
) -> bool:
    """Manda ao cliente pelo numero CENTRAL. Devolve se saiu.

    - **sem zap**: nao manda e NAO registra — o cliente desse plano nunca
      esperou WhatsApp. (Desde a etapa 1 toda barbearia e' com zap; o caminho
      fica para os planos futuros.)
    - **sem `EVOLUTION_API_URL`** (desenvolvimento): so' loga. Nao houve
      queda, so' nao ha servidor — registrar encheria o painel de mentira.
    - **envio recusado ou rede fora**: nao sai e FICA REGISTRADA. Sem fila:
      uma confirmacao tres horas atrasada e' pior que nenhuma.

    Isto desfaz a regra antiga "o central nunca fala com cliente" (spec
    2026-10-06, secao 2): risco aceito pelo Jose — se o chip cair, equipe e
    clientes param juntos ate a troca.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp] sem EVOLUTION_API_URL: %s %s", whatsapp_digitos, mensagem)
        return False

    if _enviar_aceita(cfg["instancia"], whatsapp_digitos, mensagem) is not None:
        return True

    _registrar_nao_enviada(barbearia, tipo, cliente_nome)
    return False


def _registrar_nao_enviada(barbearia, tipo: str, cliente_nome: str) -> None:
    """NUNCA levanta, pelo mesmo motivo que o envio nao levanta: esta funcao
    roda depois do commit de um agendamento que ja aconteceu, e um erro aqui
    viraria 500 numa tela onde o horario JA esta marcado — o cliente veria
    "deu erro" e apareceria na barbearia no dia certo."""
    try:
        with com_barbearia(barbearia.id):
            MensagemNaoEnviada.objects.create(
                id=str(uuid.uuid4()),
                barbearia_id=barbearia.id,
                tipo=tipo,
                cliente_nome=cliente_nome,
            )
    except Exception as e:  # noqa: BLE001 — ver o docstring
        logger.error("[whatsapp] falha ao registrar mensagem nao enviada: %s", e)


def _enviar_aceita(
    instancia: str, whatsapp_digitos: str, mensagem: str, *, digitando_ms: int | None = None,
) -> Aceita | None:
    """Fire-and-forget. Falha de WhatsApp NUNCA derruba um agendamento (§10.2).

    Porte fiel de `enviarTexto` (marcai-front/src/lib/whatsapp.ts): loga e
    NUNCA lanca. `r.ok` e conferido e o corpo da resposta e logado no erro —
    numero desconectado devolve 400, chave errada devolve 401, e sem essa
    checagem os dois passavam sem uma linha de log, com o unico sintoma sendo
    o cliente nao receber nada.

    A INSTANCIA virou parametro: era sempre a central, e agora e' a da
    barbearia quando o destinatario e' cliente. O resto do corpo nao mudou uma
    linha.

    `digitando_ms` vira o `delay` da Evolution: ela mostra "digitando..." por
    esse tempo e so' entao envia — e so' responde o POST depois disso, por
    isso o timeout cresce junto. Sem ele, sai na hora (confirmacao do site e
    avisos rodam dentro do pedido HTTP de alguem, e nao podem esperar).

    Devolve o que a Evolution aceitou (`Aceita`), ou None quando nao saiu.
    """
    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp] sem EVOLUTION_API_URL: %s %s", whatsapp_digitos, mensagem)
        return

    try:
        corpo_envio = {"number": f"55{whatsapp_digitos}", "text": mensagem}
        if digitando_ms:
            corpo_envio["delay"] = digitando_ms
        r = requests.post(
            f"{cfg['url']}/message/sendText/{instancia}",
            json=corpo_envio,
            headers={"apikey": cfg["chave"]},
            timeout=3 + (digitando_ms or 0) / 1000,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao enviar: %s", e)
        return

    if not r.ok:
        # O corpo e onde a Evolution diz o motivo — o que separa "instancia
        # desconectada" de "chave errada", as duas causas mais comuns.
        logger.error(
            "[whatsapp] envio recusado (%s) para %s: %s",
            r.status_code, whatsapp_digitos, r.text[:300],
        )
        return

    # ACEITO, nao "enviado": a Evolution devolve 201 com status PENDING mesmo
    # quando o vinculo esta morto e nada sai do lugar de verdade. Quem sabe
    # sobre entrega e o healthcheck do agendador, nao este log.
    corpo = None
    try:
        corpo = r.json()
    except ValueError:
        pass
    chave = (corpo or {}).get("key") or {}
    jid = chave.get("remoteJid")
    status = (corpo or {}).get("status", "?")
    logger.info(
        "[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid or "?", status,
    )
    # O id e o jid sobem para quem chamou. O bot guarda o id para reconhecer
    # o eco da propria resposta; a lista do dia guarda os dois para apagar.
    return Aceita(chave.get("id"), jid)


def _enviar(
    instancia: str, whatsapp_digitos: str, mensagem: str, *, digitando_ms: int | None = None,
) -> str | None:
    """O id da mensagem aceita, ou None. O que o bot sempre usou."""
    aceita = _enviar_aceita(instancia, whatsapp_digitos, mensagem, digitando_ms=digitando_ms)
    return aceita.id if aceita is not None else None


def apagar_para_todos(jid: str | None, mensagem_id: str | None) -> bool:
    """Apaga, para todos, uma mensagem que o CENTRAL mandou. Devolve se a
    Evolution aceitou. Nunca levanta: quem chama (a lista refeita) manda a
    lista nova de qualquer jeito — uma lista velha que nao sumiu e' feia, uma
    lista nova que nao chegou e' prejuizo.

    Premissa medida na Task 12 do plano: ha relato de a 2.3.7 nao apagar
    (evolution-api#592).
    """
    cfg = _config()
    if not cfg["url"] or not jid or not mensagem_id:
        return False

    try:
        r = requests.delete(
            f"{cfg['url']}/chat/deleteMessageForEveryone/{cfg['instancia']}",
            json={"id": mensagem_id, "remoteJid": jid, "fromMe": True},
            headers={"apikey": cfg["chave"]},
            timeout=3,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao apagar %s: %s", mensagem_id, e)
        return False

    if not r.ok:
        logger.error(
            "[whatsapp] apagar recusado (%s) para %s: %s",
            r.status_code, mensagem_id, r.text[:300],
        )
        return False
    return True


def numero_existe(barbearia, whatsapp_digitos: str, ip: str) -> str:
    """'existe' | 'nao_existe' | 'indeterminado'. Porte fiel de `numeroExiste`
    (whatsapp.ts). 'nao_existe' bloqueia o agendamento; 'indeterminado' deixa
    passar — indisponibilidade nao e' resposta (§10.5), entao SEM_URL, limite
    de IP estourado e falha de rede caem todos aqui, nunca em 'nao_existe'.

    So o fluxo PUBLICO chama isto — o painel nao, porque o barbeiro esta com
    o cliente na frente e o balcao e' um IP so, que o limite por hora
    morderia o uso legitimo.

    **A pergunta passou a depender do plano**, e por uma razao de produto, nao
    tecnica: sem zap, o cliente NAO VAI receber mensagem nenhuma, entao saber
    se o numero dele tem WhatsApp nao muda nada — e recusar um agendamento por
    causa disso seria perder um horario por um dado que aquele plano nao usa.
    Ali sobra a validacao de formato, que ja existe antes desta chamada.

    Com zap, a pergunta e' feita pela instancia CENTRAL (etapa 1 do numero
    central, spec 2026-10-06): e' ela que vai mandar a mensagem. Central fora
    do ar cai no mesmo `indeterminado` de sempre — deixa passar.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return "indeterminado"

    cfg = _config()
    if not cfg["url"] or not cfg["instancia"]:
        return "indeterminado"

    # Pela CENTRAL: a resposta e' a mesma para toda barbearia, entao o cache
    # e' por numero.
    chave = whatsapp_digitos
    guardado = _cache_numero.get(chave)
    if guardado and guardado["expira_em"] > _agora_ms():
        return "existe" if guardado["existe"] else "nao_existe"

    # Um formulario publico que responde "esse numero tem WhatsApp" e' uma
    # ferramenta de varredura. Sem limite, viram milhares de consultas.
    uso = _uso_por_ip.get(ip)
    if not uso or uso["janela_ate"] < _agora_ms():
        _uso_por_ip[ip] = {"contador": 1, "janela_ate": _agora_ms() + _HORA_MS}
    elif uso["contador"] >= CHECK_NUMERO_LIMITE_POR_IP_HORA:
        return "indeterminado"
    else:
        uso["contador"] += 1

    try:
        r = requests.post(
            f"{cfg['url']}/chat/whatsappNumbers/{cfg['instancia']}",
            json={"numbers": [f"55{whatsapp_digitos}"]},
            headers={"apikey": cfg["chave"]},
            timeout=CHECK_NUMERO_TIMEOUT_MS / 1000,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao verificar numero: %s", e)
        return "indeterminado"

    if not r.ok:
        return "indeterminado"

    try:
        dados = r.json()
    except ValueError:
        return "indeterminado"

    existe = isinstance(dados, list) and len(dados) > 0 and dados[0].get("exists") is True
    _cache_numero[chave] = {"existe": existe, "expira_em": _agora_ms() + CHECK_NUMERO_TTL_MS}
    return "existe" if existe else "nao_existe"


def estado_da_instancia() -> str:
    """Porte do healthcheck que vivia no `agendador` (docker-compose, antes
    da fatia 7): `"open"` quando o vinculo do WhatsApp esta de pe; senao, o
    corpo cru da resposta (o mesmo que o log gritava) — a chamadora decide o
    que fazer com isso, esta funcao so' NUNCA lanca, mesmo padrao de
    `enviar_texto`/`numero_existe` acima. Quem chama e' uma tarefa periodica,
    e uma excecao aqui mataria o tique inteiro em vez de so' logar e tentar
    de novo no proximo.

    Casamento por SUBSTRING, e nao por chave de JSON — porte fiel do `case`
    do compose (`*\"state\":\"open\"*`), que nunca precisou saber se `state`
    vem no topo do corpo ou aninhado sob `instance`. Reescrever isso como
    acesso a chave arriscaria adivinhar uma forma que o shell nunca precisou
    conhecer.
    """
    cfg = _config()
    if not cfg["url"]:
        return "sem-configuracao"

    try:
        r = requests.get(
            f"{cfg['url']}/instance/connectionState/{cfg['instancia']}",
            headers={"apikey": cfg["chave"]},
            timeout=3,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao consultar estado da instancia: %s", e)
        return "erro"

    if not r.ok:
        logger.error(
            "[whatsapp] consulta de estado recusada (%s): %s", r.status_code, r.text[:300],
        )
        return "erro"

    return "open" if '"state":"open"' in r.text else r.text[:300]
