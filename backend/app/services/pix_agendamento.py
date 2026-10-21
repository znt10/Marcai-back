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
from django.db import IntegrityError, transaction

from app.services.mensalidade import centavos, pix
from app.services.mensalidade.centavos import SemCentavoLivre
from tenant.models import Cobranca, MotivoCobranca, StatusCobranca

logger = logging.getLogger(__name__)

ALIAS = "admin"
TENTATIVAS_DE_CENTAVO = 3


def _ocupados(chave):
    """Os valores em uso por cobrancas abertas da chave, de QUALQUER barbearia
    e de qualquer motivo: o vigia so' distingue um Pix do outro pelo valor."""
    return set(
        Cobranca.objects.using(ALIAS)
        .filter(chave_pix=chave, status=StatusCobranca.ABERTA)
        .values_list("valor_centavos", flat=True)
    )


def abrir(*, barbearia_id, agendamento_id, chave, titular, cidade, base_centavos, agora):
    """Abre a cobranca do agendamento. Levanta `SemCentavoLivre` se a chave
    esgotou os 99 centavos; qualquer outra falha sobe como veio (quem chama
    decide o que fazer com o agendamento).

    O indice unico parcial e' a palavra final: se outra cobranca pegou o mesmo
    centavo entre a leitura e a gravacao, o savepoint desfaz e a busca roda de
    novo, algumas vezes."""
    chave = pix.normalizar_chave(chave)
    for _ in range(TENTATIVAS_DE_CENTAVO):
        valor = centavos.escolher(base_centavos, _ocupados(chave))
        cobranca_id = uuid.uuid4()
        try:
            with transaction.atomic(using=ALIAS):
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
        except IntegrityError:
            continue
    # Tres corridas perdidas seguidas: tratado como "sem centavo livre".
    raise SemCentavoLivre(base_centavos)


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
