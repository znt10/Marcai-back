import logging
from datetime import timedelta

from django.db import connections
from django.utils import timezone

from tenant.config import BOT_CONVERSA_GUARDADA_DIAS, ZELADOR_DIAS_DE_HISTORICO
from tenant.models import Barbearia, ConversaWhatsapp, MensagemNaoEnviada
from tenant.rls import com_barbearia

logger = logging.getLogger(__name__)


def alarmar_e_podar() -> dict:
    """Porte fiel de `docker/zelador.sh` (fatia 7): alarma envio recusado e
    poda o que envelhece, no banco DA EVOLUTION — outro banco fisico, dono
    e credencial proprios (`DATABASES["evolution"]`, settings.py), nao o
    `brutus`.

    SQL cru, sem models: o schema e' da Evolution, nao e' nosso pra
    declarar — mesma razao que o script original usava `psql` puro em vez
    de falar com um ORM.
    """
    with connections["evolution"].cursor() as cur:
        # O WhatsApp rejeita de forma ASSINCRONA: quando a recusa chega, a
        # Evolution ja devolveu 201 ao app e ninguem mais esta olhando.
        # `status = 'ERROR'` e' o UNICO registro de que a mensagem nao foi
        # entregue — em 10/08 a falta deste alarme custou horas: log limpo
        # dos dois lados, instancia `open`, soquete respondendo, e nenhuma
        # mensagem chegando.
        cur.execute('SELECT count(*) FROM "MessageUpdate" WHERE status = \'ERROR\'')
        recusados = cur.fetchone()[0]

        if recusados:
            logger.warning(
                "[zelador] !!! %s ENVIO(S) RECUSADO(S) PELO WHATSAPP — o vinculo "
                "aceita e nao transmite: confira Aparelhos conectados no celular "
                "e depois rode whatsapp:qr",
                recusados,
            )
        else:
            logger.info("[zelador] nenhum envio recusado")

        # A poda existe porque o rastreio de status EXIGE guardar o texto que
        # NOS mandamos (medido em 10/08: com `DATABASE_SAVE_DATA_NEW_MESSAGE
        # =false` a `MessageUpdate` fica vazia tambem — nao existe "so o
        # status"). Sem podar, o historico cresceria para sempre.
        #
        # `MessageUpdate` primeiro: ela referencia `Message`.
        cur.execute(
            """
            DELETE FROM "MessageUpdate"
             WHERE "messageId" IN (
               SELECT id FROM "Message"
                WHERE to_timestamp("messageTimestamp")
                      < now() - make_interval(days => %s))
            """,
            [ZELADOR_DIAS_DE_HISTORICO],
        )
        podados_message_update = cur.rowcount

        cur.execute(
            """
            DELETE FROM "Message"
             WHERE to_timestamp("messageTimestamp")
                   < now() - make_interval(days => %s)
            """,
            [ZELADOR_DIAS_DE_HISTORICO],
        )
        podados_message = cur.rowcount

    return {
        "recusados": recusados,
        "podados_message_update": podados_message_update,
        "podados_message": podados_message,
        "podadas_nao_enviadas": _podar_nao_enviadas(),
        "podadas_conversas": _podar_conversas(),
    }


def _podar_nao_enviadas() -> int:
    """As "N mensagens nao enviadas" do painel, depois de 7 dias.

    Outro banco e outra logica do resto do zelador — este e o `brutus`, com
    RLS, entao a poda e tenant a tenant. O prazo e o mesmo
    (`ZELADOR_DIAS_DE_HISTORICO`) porque a razao e a mesma: passado o prazo, a
    linha ja nao informa nada acionavel. Uma confirmacao que nao saiu ha dez
    dias descreve um horario que ja aconteceu (ou nao) — o dono nao tem o que
    fazer com ela, e o contador do painel viraria um numero que so cresce e que
    ninguem consegue zerar.
    """
    limite = timezone.now() - timedelta(days=ZELADOR_DIAS_DE_HISTORICO)
    podadas = 0
    for b in Barbearia.objects.all():
        with com_barbearia(b.id):
            apagadas, _ = MensagemNaoEnviada.objects.filter(criado_em__lt=limite).delete()
        podadas += apagadas
    return podadas


def _podar_conversas() -> int:
    """Conversa do bot parada ha mais de BOT_CONVERSA_GUARDADA_DIAS.

    Conversa e' estado de minutos: depois de 20 ela ja recomeca do menu. Passado
    o prazo, a linha so' guardaria o numero de alguem sem motivo nenhum.

    A conversa MUDA fica, mesmo velha: `mudo_ate` no futuro quer dizer que
    alguem da barbearia esta falando com essa pessoa, e apagar a linha faria o
    bot voltar a responder por cima.
    """
    agora = timezone.now()
    limite = agora - timedelta(days=BOT_CONVERSA_GUARDADA_DIAS)
    podadas = 0
    for b in Barbearia.objects.all():
        with com_barbearia(b.id):
            apagadas, _ = (
                ConversaWhatsapp.objects.filter(atualizado_em__lt=limite)
                .exclude(mudo_ate__gt=agora)
                .delete()
            )
        podadas += apagadas
    return podadas
