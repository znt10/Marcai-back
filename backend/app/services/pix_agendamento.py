"""A cobranca Pix de um agendamento marcado pelo site: abrir e cancelar.

`Cobranca` fica fora do RLS e o `brutus_app` so' le: toda escrita daqui vai
pelo alias `admin`, como na mensalidade (e com a mesma regra de centavos).
Nada aqui abre transacao no tenant: a FK `Cobranca.agendamento` e' conferida
no COMMIT da cobranca, por OUTRA conexao, entao o agendamento tem de estar
comitado antes — quem chama `abrir` garante isso."""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings

from app.services.mensalidade import centavos, pix
from tenant.models import Cobranca, MotivoCobranca, StatusCobranca

logger = logging.getLogger(__name__)

ALIAS = "admin"


def _ocupados(chave):
    return centavos.ocupados(chave, using=ALIAS)


def abrir(*, barbearia_id, agendamento_id, chave, titular, cidade, base_centavos, agora):
    """Abre a cobranca do agendamento. Levanta `SemCentavoLivre` se a chave
    esgotou os 99 centavos (ou se perdeu a disputa pelo centavo tres vezes);
    qualquer outra falha sobe como veio (quem chama decide o que fazer com o
    agendamento). A escolha e a corrida pelo indice unico sao as da
    mensalidade (`centavos.criar_com_centavo_livre`)."""
    chave = pix.normalizar_chave(chave)

    def criar(valor):
        cobranca_id = uuid.uuid4()
        return Cobranca.objects.using(ALIAS).create(
            id=cobranca_id,
            barbearia_id=barbearia_id,
            agendamento_id=agendamento_id,
            motivo=MotivoCobranca.AGENDAMENTO,
            chave_pix=chave,
            valor_base_centavos=base_centavos,
            valor_centavos=valor,
            copia_e_cola=pix.copia_e_cola(
                chave=chave,
                nome=titular,
                cidade=cidade or "BRASIL",
                valor=Decimal(valor) / 100,
                identificador=pix.identificador(cobranca_id),
            ),
            expira_em=agora + timedelta(minutes=settings.PIX_AGENDAMENTO_PRAZO_MIN),
        )

    return centavos.criar_com_centavo_livre(
        chave, base_centavos, criar, ocupados_de=lambda c: _ocupados(c), using=ALIAS,
    )


def cancelar_abertas(agendamento_ids) -> None:
    """Cancela a cobranca ABERTA de cada agendamento (o centavo volta a ficar
    livre). Chamado DEPOIS do commit que cancelou o agendamento. Se falhar, so'
    registra: o cliente ja' cancelou, e a cobranca que sobra morre no prazo
    dela."""
    ids = list(agendamento_ids)
    if not ids:
        return
    try:
        Cobranca.objects.using(ALIAS).filter(
            agendamento_id__in=ids, status=StatusCobranca.ABERTA,
        ).update(status=StatusCobranca.CANCELADA)
    except Exception:
        logger.exception("[pix] cobranca de agendamento cancelado nao foi cancelada: %s", ids)
