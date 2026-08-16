import logging

from django.db import connections

from tenant.config import ZELADOR_DIAS_DE_HISTORICO

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
    }
