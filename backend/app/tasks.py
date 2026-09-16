import logging
from datetime import datetime, timezone

from celery import shared_task

from app.services.lembrete import enviar_pendentes
from app.services.lista_do_dia import enviar as enviar_lista_do_dia
from app.services.whatsapp import estado_da_instancia
from app.services.whatsapp_eventos import aplicar_estado
from app.services.whatsapp_instancias import consultar_estado, garantir_instancia
from app.services.zelador import alarmar_e_podar
from tenant.models import Barbearia, EstadoInstancia, PlanoBarbearia, WhatsappInstancia
from tenant.rls import com_barbearia

logger = logging.getLogger(__name__)


@shared_task
def lembretes() -> int:
    """Substitui o `curl -X POST .../api/cron/lembretes` do `agendador`
    (docker-compose, antes da fatia 7). Chama `enviar_pendentes` DIRETO —
    sem HTTP — porque a tarefa roda dentro do mesmo processo Django: o
    salto por rota (com toda a via-crucis de `TenantMiddleware`,
    `ClienteMiddleware` e o `Host` forjado que o `agendador` precisava
    mandar) deixa de ser necessario pro disparo AGENDADO.

    A rota `POST /api/cron/lembretes` continua existindo, pro gancho
    manual/externo — e' seguro rodar as duas: `enviar_pendentes` e'
    idempotente por `lembrete_enviado_em`.
    """
    return enviar_pendentes(datetime.now(timezone.utc))


@shared_task
def whatsapp_healthcheck() -> str:
    """Substitui a metade `connectionState` do `agendador`. So' loga — a
    outra metade (o selo na tela do admin) e' card separado no Trello."""
    estado = estado_da_instancia()
    if estado != "open":
        logger.warning(
            "[agendador] !!! WHATSAPP FORA DO AR: %s — rode: npm run whatsapp:qr",
            estado,
        )
    return estado


@shared_task
def lista_do_dia() -> int:
    """As 07:00 de Sao Paulo (o `CELERY_TIMEZONE` ja e esse), pelo numero
    CENTRAL, nos dois planos.

    E a mensagem que faz o plano sem zap valer alguma coisa: la o cliente nao
    recebe nada, e sem isto o barbeiro tambem nao saberia da agenda sem abrir
    o painel.
    """
    return enviar_lista_do_dia(datetime.now(timezone.utc))


@shared_task
def conferir_instancias() -> dict:
    """A rede de seguranca do webhook, a cada cinco minutos.

    O webhook resolve o caso normal e resolve em segundos. Esta tarefa existe
    para o caso anormal, que e o unico que machuca: um evento perdido deixa o
    painel jurando "conectado" enquanto nenhuma mensagem sai, e ninguem
    descobre isso olhando — descobre pelo cliente que nao apareceu.

    Duas coisas por barbearia com zap, e so uma delas por tique:
    `PENDENTE` significa "a Evolution ainda nao sabe que isto existe", entao o
    caminho e' CRIAR (nao adianta perguntar o estado de quem nao existe la);
    qualquer outro estado e' uma PERGUNTA, e a resposta passa pela mesma
    transicao que o webhook usaria — as regras vivem em `whatsapp_eventos`
    justamente para nao existirem duas.

    `Barbearia` esta fora do RLS (lida direto); `WhatsappInstancia` nao, entao
    cada tenant precisa da propria consulta escopada — o mesmo laco
    tenant-a-tenant de `enviar_pendentes`.

    Desativada nao entra: desativar ja apagou a instancia, e perguntar por ela
    traria 404, que marcaria `PENDENTE`, que faria o proximo tique RECRIAR o
    numero de uma barbearia que saiu.
    """
    criadas = conferidas = corrigidas = 0

    for b in Barbearia.objects.filter(ativo=True, plano=PlanoBarbearia.COM_ZAP):
        with com_barbearia(b.id):
            linha = WhatsappInstancia.objects.filter(barbearia_id=b.id).first()
        if linha is None:
            # Acontece de verdade: plano trocado com a Evolution fora do ar,
            # linha apagada a mao. Pular e' o certo — a barbearia seguinte nao
            # tem culpa, e um `None` nao tratado aqui mataria o tique inteiro.
            logger.warning("[conferir-instancias] barbearia %s com zap e sem linha", b.id)
            continue

        if linha.estado == EstadoInstancia.PENDENTE:
            garantir_instancia(b)
            criadas += 1
            continue

        conferidas += 1
        if aplicar_estado(b.id, linha, consultar_estado(linha.nome)):
            corrigidas += 1
            logger.info(
                "[conferir-instancias] %s estava %s e foi corrigida", linha.nome, linha.estado,
            )

    return {"criadas": criadas, "conferidas": conferidas, "corrigidas": corrigidas}


@shared_task
def zelador() -> dict:
    """Substitui o `while true` de `docker/zelador.sh`."""
    return alarmar_e_podar()
