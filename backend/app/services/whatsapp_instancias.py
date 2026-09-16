"""O ciclo de vida da instancia de WhatsApp DA BARBEARIA.

Este modulo cuida do VINCULO (criar, apagar, perguntar como esta, pedir o QR);
quem manda mensagem continua sendo `whatsapp.py`. A divisao importa porque as
duas coisas falham de jeitos diferentes: mensagem nao enviada e' um cliente
sem aviso, vinculo quebrado e' a barbearia inteira muda.

Duas regras valem em toda funcao daqui:

1. **Nunca levanta.** Todo chamador esta no meio de outra coisa — cadastrar
   barbearia, rodar um tique do Celery, responder um pedido do painel — e
   nenhuma dessas coisas pode morrer porque a Evolution nao atendeu. Mesmo
   contrato de `enviar_texto`/`numero_existe`.
2. **Indisponibilidade nao e resposta.** Falha de rede vira `None` ("nao sei")
   ou nenhuma mudanca de estado, nunca um estado inventado. Gravar
   `DESCONECTADO` porque a rede piscou faria a faixa do painel mentir para a
   barbearia inteira.

A chave da Evolution e a GLOBAL (`EVOLUTION_API_KEY`): as instancias por
barbearia nao tem chave propria, e nao e' segredo que se possa entregar ao
tenant de qualquer forma — quem fala com a Evolution e' sempre o Marcai.
"""

import logging
import os
import uuid

import requests
from django.utils import timezone

from tenant.models import EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

logger = logging.getLogger(__name__)

# Prefixo do nome da instancia do lado da Evolution. E' a UNICA coisa que liga
# um evento de webhook a uma barbearia, entao ele nao pode depender de nada
# configuravel — dominio, plano ou nome da barbearia mudam; o id, nao.
PREFIXO = "marcai-"

# Curto de proposito. Quem chama esta no caminho de um pedido ou de um tique,
# e esperar 30s pela Evolution e' pior do que nao saber: o estado que falta
# aqui a conferencia periodica descobre no proximo ciclo. Medido contra a
# 2.3.7: `webhook/set` e `connectionState` respondem em MILISSEGUNDOS, entao
# 5s ja e' folga enorme para elas.
TIMEOUT_S = 5

# A criacao e outra coisa, e isto foi medido doendo: `POST /instance/create`
# sobe um socket Baileys antes de responder e levou **5,3s** numa maquina de
# desenvolvimento ociosa — logo acima dos 5s acima. Com o timeout curto o
# cadastro de uma barbearia com zap falhava toda vez, e falhava do jeito mais
# confuso possivel: a instancia era criada do lado de la assim mesmo (o
# trabalho continua depois que a conexao cai), a linha ficava `PENDENTE`, e o
# dono so via o QR quando a conferencia de 5 minutos passasse.
#
# 15s, e nao 30: isto roda dentro do pedido HTTP do admin (via `on_commit`),
# entao o numero e' quanto tempo alguem fica olhando para uma tela travada no
# pior caso. Tres vezes o medido cobre uma VPS carregada; o que passar disso
# cai na conferencia periodica, que conserta sozinha — e o `create` repetido
# la bate no 403 idempotente em vez de criar uma segunda instancia.
TIMEOUT_CRIACAO_S = 15

# Assinados em MAIUSCULO; chegam minusculos e com ponto. MESSAGES_UPSERT so'
# entra com o bot ligado: barbearia sem bot nunca manda uma mensagem de
# cliente para o Marcai (spec, secao 7).
EVENTOS_SEM_BOT = ["CONNECTION_UPDATE", "QRCODE_UPDATED"]
EVENTOS_COM_BOT = EVENTOS_SEM_BOT + ["MESSAGES_UPSERT"]


def _config() -> dict[str, str]:
    """Lida a cada chamada, e nao no topo do modulo, pela mesma razao do
    `_config()` de `whatsapp.py`: o teste troca as variaveis entre casos, e uma
    constante de modulo congelaria o primeiro valor."""
    return {
        "url": os.environ.get("EVOLUTION_API_URL", ""),
        "chave": os.environ.get("EVOLUTION_API_KEY", ""),
        "webhook_url": os.environ.get("WHATSAPP_WEBHOOK_URL", ""),
        "webhook_segredo": os.environ.get("WHATSAPP_WEBHOOK_SEGREDO", ""),
        "dominio": os.environ.get("DOMINIO_BASE", "localhost"),
    }


def nome_da_instancia(barbearia_id) -> str:
    return f"{PREFIXO}{barbearia_id}"


def barbearia_id_do_nome(nome: str) -> str | None:
    """A volta, e ela e' a porta de entrada do webhook: o que chega ali vem da
    rede e nao merece confianca nenhuma.

    O formato do uuid e' CONFERIDO, e nao so' o prefixo. Sem isso,
    `marcai-'; DROP ...` viraria uma consulta com lixo dentro — o ORM
    parametriza e nada explodiria, mas o lugar de recusar entrada torta e' na
    entrada, nao na sorte da camada seguinte.
    """
    if not nome or not nome.startswith(PREFIXO):
        return None
    resto = nome[len(PREFIXO):]
    try:
        return str(uuid.UUID(resto))
    except ValueError:
        return None


def _cabecalhos_do_webhook(cfg: dict[str, str]) -> dict[str, str]:
    """Os tres cabecalhos que a Evolution repassa verbatim (medido na 2.3.7,
    fatia 0). Cada um resolve uma barreira diferente do caminho, e tirar
    qualquer um deles faz o webhook morrer ANTES da view, sem log nenhum do
    nosso lado:

    - `Host`: o pedido chega pela rede interna do compose (`http://api:8000`),
      onde o Host real seria `api` — que o `ALLOWED_HOSTS` recusa com 400. Com
      o host de admin ele passa, e o `TenantMiddleware` o trata como pedido de
      plataforma, sem tenant. E o mesmo truque que o cron ja usava.
    - `x-brutus-cliente`: o `ClienteMiddleware` recusa com 403 todo verbo que
      escreve sem ele. O valor nao e' segredo e nao importa; o que protege e' a
      exigencia (ela obriga preflight de CORS no navegador).
    - `x-marcai-webhook`: esta sim e' a credencial, conferida contra
      `WHATSAPP_WEBHOOK_SEGREDO`.
    """
    return {
        "Host": f"admin.{cfg['dominio']}",
        "x-brutus-cliente": "evolution",
        "x-marcai-webhook": cfg["webhook_segredo"],
    }


def garantir_instancia(barbearia) -> None:
    """Cria a instancia na Evolution e aponta o webhook para ca.

    Idempotente de proposito: a conferencia periodica chama isto a cada cinco
    minutos para toda barbearia `PENDENTE`, e a troca de plano chama de novo
    para uma barbearia que talvez ja tenha instancia. Uma instancia que ja
    existe (403 "already in use") nao e falha — e' metade do trabalho ja
    feita, e o webhook e' reaplicado mesmo assim, que e' o unico caminho que
    conserta um webhook apontando para o lugar errado.

    Nao cria a LINHA: ela nasce no cadastro, dentro da transacao que cria a
    barbearia, e este modulo so a encontra. Sem linha, nao ha o que garantir.
    """
    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None:
        logger.warning(
            "[whatsapp-instancia] barbearia %s sem linha de instancia; nada a garantir",
            barbearia.id,
        )
        return

    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp-instancia] sem EVOLUTION_API_URL: %s fica PENDENTE", linha.nome)
        return

    try:
        r = requests.post(
            f"{cfg['url']}/instance/create",
            json={
                "instanceName": linha.nome,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
            },
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_CRIACAO_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-instancia] falha ao criar instancia %s: %s", linha.nome, e)
        return

    # 403 com "already in use" e' sucesso disfarcado (medido na 2.3.7).
    # Qualquer outra recusa e' recusa: para aqui e deixa `PENDENTE`, para a
    # conferencia periodica tentar de novo.
    ja_existia = r.status_code == 403 and "already in use" in r.text
    if not r.ok and not ja_existia:
        logger.error(
            "[whatsapp-instancia] criacao recusada (%s) para %s: %s",
            r.status_code, linha.nome, r.text[:300],
        )
        return

    if not _aplicar_webhook(cfg, linha.nome, bot=linha.bot_ativo):
        # Instancia sem webhook e' pior que instancia nenhuma: ela conectaria
        # e nos nunca saberiamos. Fica `PENDENTE` para a conferencia tentar de
        # novo — e o `create` repetido cai no 403 idempotente acima.
        return

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
            estado=EstadoInstancia.AGUARDANDO_QR, atualizado_em=timezone.now(),
        )


def _aplicar_webhook(cfg: dict[str, str], nome: str, *, bot: bool = False) -> bool:
    if not cfg["webhook_url"]:
        logger.error("[whatsapp-instancia] sem WHATSAPP_WEBHOOK_URL: %s ficaria surdo", nome)
        return False

    try:
        r = requests.post(
            f"{cfg['url']}/webhook/set/{nome}",
            json={
                "webhook": {
                    "enabled": True,
                    "url": cfg["webhook_url"],
                    "headers": _cabecalhos_do_webhook(cfg),
                    "byEvents": False,
                    # SEMPRE `true`. Medido na fatia 0b: mesmo com `false` a
                    # Evolution mandou uma foto inteira (`message.base64`,
                    # ~217 KB) dentro do evento — a opcao nao tira midia
                    # nenhuma e so' arriscava o QR, que continua chegando por
                    # `pedir_qr`. A protecao real contra corpo grande e' o
                    # limite de tamanho do webhook (Task 11).
                    "base64": True,
                    "events": EVENTOS_COM_BOT if bot else EVENTOS_SEM_BOT,
                }
            },
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-instancia] falha ao aplicar webhook em %s: %s", nome, e)
        return False

    if not r.ok:
        logger.error(
            "[whatsapp-instancia] webhook recusado (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
        return False
    return True


def aplicar_assinatura(nome: str, *, bot: bool) -> bool:
    """Reescreve a lista de eventos de uma instancia que ja existe. Medido na
    fatia 0: `webhook/set` aceita isso com a instancia conectada, sem derrubar
    a conexao."""
    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp-instancia] sem EVOLUTION_API_URL: assinatura de %s nao muda", nome)
        return False
    return _aplicar_webhook(cfg, nome, bot=bot)


def apagar_instancia(barbearia) -> None:
    """Desliga o vinculo e apaga a linha. Chamado ao sair do plano com zap e ao
    desativar a barbearia.

    O logout vem ANTES do delete: apagar sem deslogar deixa a sessao pendurada
    no celular do dono, que continua listando um aparelho conectado que
    ninguem mais controla.

    A linha some MESMO se a Evolution nao atender, e isso e uma escolha. O que
    esta acontecendo aqui e' uma troca de plano, e trava-la numa
    indisponibilidade da Evolution deixaria a barbearia presa num estado que
    ninguem pediu. O preco e' uma instancia orfa do lado de la — barulhenta no
    log, de proposito, porque ninguem vai procura-la sozinho.
    """
    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None:
        return

    cfg = _config()
    if cfg["url"]:
        for rota in ("logout", "delete"):
            try:
                r = requests.delete(
                    f"{cfg['url']}/instance/{rota}/{linha.nome}",
                    headers={"apikey": cfg["chave"]},
                    timeout=TIMEOUT_S,
                )
                if not r.ok:
                    logger.error(
                        "[whatsapp-instancia] %s recusado (%s) para %s: fica orfa la",
                        rota, r.status_code, linha.nome,
                    )
            except requests.RequestException as e:
                logger.error(
                    "[whatsapp-instancia] falha no %s de %s (%s): fica orfa la",
                    rota, linha.nome, e,
                )

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).delete()


def desconectar_aparelho(nome: str) -> bool:
    """Logout SEM delete: a instancia continua existindo do lado de la e volta
    a gerar QR. E o "trocar de celular" do painel.

    A diferenca para `apagar_instancia` e' a intencao: la o vinculo acaba (a
    barbearia saiu do plano), aqui ele so troca de aparelho. Apagar a
    instancia neste caminho custaria uma recriacao e um nome novo para
    resolver o que um logout resolve.
    """
    cfg = _config()
    if not cfg["url"]:
        return False

    try:
        r = requests.delete(
            f"{cfg['url']}/instance/logout/{nome}",
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-instancia] falha ao deslogar %s: %s", nome, e)
        return False

    if not r.ok:
        logger.error(
            "[whatsapp-instancia] logout recusado (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
        return False
    return True


def consultar_estado(nome: str) -> str | None:
    """Como a Evolution ve a instancia, em `EstadoInstancia`. `None` quer dizer
    "nao sei" — e quem chama tem que tratar isso como "nao mude nada".

    Tres respostas viram `None`: falha de rede, recusa que nao seja 404, e
    `connecting`. O `connecting` e' o intervalo entre pedir o QR e alguem
    escanear: chama-lo de desconectado faria a faixa do painel piscar toda vez
    que o dono abrisse a tela do QR.

    O 404 e' o caso interessante — a instancia sumiu do lado de la (volume
    perdido, apagada a mao) — e vira `PENDENTE`, que e' justamente o estado que
    manda a conferencia periodica recria-la.

    A leitura do corpo e por SUBSTRING, como em `estado_da_instancia`: o
    `state` aparece no topo ou aninhado sob `instance` conforme a rota, e o
    casamento frouxo atravessa as duas formas sem precisar adivinhar qual veio.
    """
    cfg = _config()
    if not cfg["url"]:
        return None

    try:
        r = requests.get(
            f"{cfg['url']}/instance/connectionState/{nome}",
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-instancia] falha ao consultar %s: %s", nome, e)
        return None

    if r.status_code == 404:
        return EstadoInstancia.PENDENTE
    if not r.ok:
        logger.error(
            "[whatsapp-instancia] consulta recusada (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
        return None

    if '"state":"open"' in r.text:
        return EstadoInstancia.CONECTADO
    if '"state":"close"' in r.text or '"state":"refused"' in r.text:
        return EstadoInstancia.DESCONECTADO
    return None


def pedir_qr(nome: str) -> str | None:
    """Pede um QR novo. Usado quando o dono abre a tela e nao ha QR guardado —
    o caminho normal e' o webhook trazer o QR sozinho, e este aqui e' a saida
    para quem chegou depois de o ultimo ter expirado.

    Resposta sem `base64` nao e erro: instancia ja conectada responde assim, e
    nao ha QR a mostrar mesmo.
    """
    cfg = _config()
    if not cfg["url"]:
        return None

    try:
        r = requests.get(
            f"{cfg['url']}/instance/connect/{nome}",
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-instancia] falha ao pedir QR de %s: %s", nome, e)
        return None

    if not r.ok:
        logger.error(
            "[whatsapp-instancia] QR recusado (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
        return None

    try:
        corpo = r.json()
    except ValueError:
        return None
    return corpo.get("base64") or None
