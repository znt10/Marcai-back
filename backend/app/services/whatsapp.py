import logging
import os
import time
import uuid

import requests

from tenant.config import (
    CHECK_NUMERO_LIMITE_POR_IP_HORA,
    CHECK_NUMERO_TIMEOUT_MS,
    CHECK_NUMERO_TTL_MS,
)
from tenant.models import (
    Barbearia,
    EstadoInstancia,
    MensagemNaoEnviada,
    PlanoBarbearia,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia
from tenant.telefone import canonico

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


def enviar_a_equipe(whatsapp_digitos: str, mensagem: str) -> None:
    """Manda pela instancia CENTRAL do Marcai — barbeiro, dono, convite.

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
    """O aviso de equipe de UMA barbearia. Sai pelo central, como
    `enviar_a_equipe` — menos quando o destinatario E' o numero da propria
    barbearia.

    E' o barbeiro sozinho que conectou o proprio celular como numero da
    barbearia. Pelo central, o aviso chega de um numero que ele nunca salvou;
    pela instancia dele, cai no "conversar comigo mesmo" (medido: `sendText`
    de uma instancia para o proprio numero responde 201). Nao ha cliente
    nenhum nesse caminho, entao a regra "o central nunca fala com cliente"
    continua inteira.

    Com zap, ativa e CONECTADA — qualquer outra coisa cai no central, que
    entrega mesmo com o aparelho da barbearia fora. A leitura e' curta e o
    envio fica fora dela: `com_barbearia` nao aninha, e segurar transacao
    durante uma chamada de rede nao ajuda ninguem.
    """
    alvo = canonico(whatsapp_digitos)
    instancia = None
    if alvo is not None and Barbearia.objects.filter(
        id=barbearia_id, ativo=True, plano=PlanoBarbearia.COM_ZAP,
    ).exists():
        with com_barbearia(barbearia_id):
            linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia_id).first()
        if (
            linha is not None
            and linha.estado == EstadoInstancia.CONECTADO
            and canonico(linha.numero_conectado) == alvo
        ):
            instancia = linha.nome

    if instancia is None:
        enviar_a_equipe(whatsapp_digitos, mensagem)
        return
    _enviar(instancia, whatsapp_digitos, mensagem)


def enviar_ao_cliente(
    barbearia, whatsapp_digitos: str, mensagem: str, *, tipo: str, cliente_nome: str,
) -> bool:
    """Manda pela instancia DA BARBEARIA. Devolve se saiu.

    Tres caminhos, e cada um e uma decisao ja tomada:

    - **sem zap**: nao manda e NAO registra. O cliente desse plano nunca
      esperou WhatsApp nenhum — ele viu a confirmacao na tela. Registrar aqui
      encheria o painel de "nao enviadas" que nao representam perda nenhuma.
    - **com zap, conectado**: sai pelo numero da barbearia.
    - **com zap, fora do ar**: nao sai e FICA REGISTRADA. Sem fila e sem
      fallback pelo central: uma confirmacao que chega tres horas depois,
      quando o cliente ja ligou para perguntar, e pior que nenhuma; e mandar
      pelo central faria o cliente receber de um numero que ele nao conhece.
      O que a linha compra e o painel poder dizer "N mensagens nao enviadas" —
      o dono descobre a queda pelo prejuizo, e nao so pela faixa.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()

    if linha is not None and linha.estado == EstadoInstancia.CONECTADO:
        _enviar(linha.nome, whatsapp_digitos, mensagem)
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


def _enviar(instancia: str, whatsapp_digitos: str, mensagem: str) -> str | None:
    """Fire-and-forget. Falha de WhatsApp NUNCA derruba um agendamento (§10.2).

    Porte fiel de `enviarTexto` (marcai-front/src/lib/whatsapp.ts): loga e
    NUNCA lanca. `r.ok` e conferido e o corpo da resposta e logado no erro —
    numero desconectado devolve 400, chave errada devolve 401, e sem essa
    checagem os dois passavam sem uma linha de log, com o unico sintoma sendo
    o cliente nao receber nada.

    A INSTANCIA virou parametro: era sempre a central, e agora e' a da
    barbearia quando o destinatario e' cliente. O resto do corpo nao mudou uma
    linha.

    Devolve o id da mensagem aceita, ou None.
    """
    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp] sem EVOLUTION_API_URL: %s %s", whatsapp_digitos, mensagem)
        return

    try:
        r = requests.post(
            f"{cfg['url']}/message/sendText/{instancia}",
            json={"number": f"55{whatsapp_digitos}", "text": mensagem},
            headers={"apikey": cfg["chave"]},
            timeout=3,
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
    chave = (corpo or {}).get("key", {})
    jid = chave.get("remoteJid", "?")
    status = (corpo or {}).get("status", "?")
    logger.info("[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid, status)
    # O id sobe para quem chamou. Os envios de sempre o ignoram; o bot o
    # guarda para reconhecer o eco da propria mensagem no webhook.
    return chave.get("id")


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

    Com zap, a pergunta e' feita pela instancia DA BARBEARIA: a central pode
    nem ter vinculo de pe, e perguntar por ela devolveria `indeterminado` para
    todo mundo. Instancia da barbearia fora do ar cai no mesmo
    `indeterminado` de sempre — deixa passar.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return "indeterminado"

    cfg = _config()
    if not cfg["url"]:
        return "indeterminado"

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None or linha.estado != EstadoInstancia.CONECTADO:
        return "indeterminado"

    # Chave com a barbearia dentro: o cache guarda a resposta de UMA instancia,
    # e uma instancia desconectada responde diferente da conectada ao lado.
    chave = f"{barbearia.id}:{whatsapp_digitos}"
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
            f"{cfg['url']}/chat/whatsappNumbers/{linha.nome}",
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
