"""A cobranca Pix de um agendamento marcado pelo site: abrir e cancelar.

`Cobranca` fica fora do RLS e o `brutus_app` so' le: toda escrita daqui vai
pelo alias `admin`, como na mensalidade (e com a mesma regra de centavos).
Nada aqui abre transacao no tenant: a FK `Cobranca.agendamento` e' conferida
no COMMIT da cobranca, por OUTRA conexao, entao o agendamento tem de estar
comitado antes — quem chama `abrir` garante isso."""

import logging
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from contextlib import contextmanager

from django.db import connections, transaction
from django.db.models import Exists, OuterRef

from app.services import mensagens
from app.services.mensalidade import centavos, pix
from app.services.whatsapp import enviar_a_equipe_da, enviar_ao_cliente
from tenant.models import (
    Agendamento,
    Barbearia,
    Cobranca,
    ComoFoiPaga,
    MotivoCobranca,
    StatusAgendamento,
    StatusCobranca,
    TipoMensagem,
)
from tenant.rls import com_barbearia

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


def valor_pago(agendamento_id, status_do_agendamento: str) -> int | None:
    """Quanto o cliente pagou, se o horario que esta sendo cancelado estava
    pago (centavos, com o centavo a mais); None se nao. Chamado SOB A TRAVA do
    agendamento, com o status ja' relido.

    Pago e' (a) cobranca PAGA, ou (b) agendamento CONFIRMADO com cobranca
    ligada que nao foi cancelada: so' o "recebi" confirma um agendamento que
    tinha cobranca, e a escrita dela (outra conexao) pode ainda nao ter chegado.
    Le pela conexao de quem chama: `Cobranca` e' legivel pelo `brutus_app`."""
    if status_do_agendamento != StatusAgendamento.CONFIRMADO:
        return None
    return (
        Cobranca.objects.filter(agendamento_id=agendamento_id)
        .exclude(status=StatusCobranca.CANCELADA)
        .values_list("valor_centavos", flat=True)
        .first()
    )


def fechar_cobrancas_do_cancelamento(aguardando_ids, pagos_ids, agora) -> None:
    """Depois do commit do cancelamento: quem esperava o Pix perde a cobranca
    (CANCELADA) e quem ja' estava pago a tem confirmada (PAGA, nunca
    CANCELADA: o dinheiro entrou e o centavo nao pode voltar a ficar livre)."""
    cancelar_abertas(aguardando_ids)
    ids = list(pagos_ids)
    if not ids:
        return
    try:
        Cobranca.objects.using(ALIAS).filter(
            agendamento_id__in=ids,
            status__in=[StatusCobranca.ABERTA, StatusCobranca.EXPIRADA],
        ).update(status=StatusCobranca.PAGA, paga_em=agora, como_foi_paga=ComoFoiPaga.MANUAL)
    except Exception:
        logger.exception("[pix] cobranca de agendamento pago e cancelado nao foi fechada: %s", ids)


def avisar_cancelamento_pago(barbearia_id, cancelamentos, *, pelo_cliente: bool) -> None:
    """O horario cancelado estava pago: o barbeiro dele recebe no zap que
    precisa devolver o Pix (o Marcai nao move dinheiro). Chamado DEPOIS do
    commit do cancelamento; `cancelamentos` e' uma lista de dicts com
    `cliente_nome`, `barbeiro_whatsapp`, `inicio` e `valor_centavos`."""
    for c in cancelamentos:
        texto = mensagens.msg_barbeiro_cancelou_pago(
            cliente_nome=c["cliente_nome"], inicio=c["inicio"],
            valor_centavos=c["valor_centavos"], pelo_cliente=pelo_cliente,
        )
        transaction.on_commit(
            lambda c=c, texto=texto: _enviar_a_equipe(barbearia_id, c["barbeiro_whatsapp"], texto)
        )


def _enviar_a_equipe(barbearia_id, whatsapp, texto) -> None:
    try:
        enviar_a_equipe_da(barbearia_id, whatsapp, texto)
    except Exception:
        logger.exception("[pix] aviso de devolucao nao saiu para %s", whatsapp)


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


# ---- a varredura: o prazo do Pix venceu
#
# Duas conexoes, nenhuma transacao entre elas: o agendamento mora no tenant
# (RLS, conexao `default`) e a cobranca fora dele (alias `admin`). A regra que
# faz as duas pontas se acertarem:
#
#   1. QUEM DECIDE O ESTADO E' O AGENDAMENTO, sob `SELECT ... FOR UPDATE` na
#      linha dele. "Recebi" e varredura brigam por essa trava: quem chega
#      primeiro decide, o outro le o resultado e age em cima dele.
#   2. A COBRANCA SEGUE, depois do commit, com UPDATE condicional (`WHERE
#      status = ...`): nunca sobrescreve um estado que outro ja' decidiu.
#   3. Se algo parar entre os dois commits, a proxima varredura reconcilia:
#      CONFIRMADO com cobranca aberta/expirada -> PAGA; EXPIRADO -> EXPIRADA;
#      CANCELADO -> CANCELADA.
#
# O aviso ao cliente sai so' de quem virou o agendamento de AGUARDANDO para
# EXPIRADO sob a trava; a segunda rodada ja' o encontra EXPIRADO e cala.

# A folga de (a): entre o commit do agendamento e a abertura da cobranca passam
# milissegundos, mas um agendamento sem cobranca so' e' dado como orfao depois
# do prazo mais este minuto.
FOLGA_DO_ORFAO = timedelta(minutes=1)
# Chave da trava consultiva do Postgres que impede duas rodadas do beat ao mesmo tempo.
TRAVA_DA_VARREDURA = 7_251_001


def expirar_vencidos(agora, *, barbearia_id=None, barbeiro_id=None) -> dict:
    """Expira o que passou do prazo e reconcilia cobranca com agendamento.
    Sem argumentos: a varredura inteira do beat. Com `barbearia_id` +
    `barbeiro_id`: so' as cobrancas daquele barbeiro, para `marcar()` nao
    depender do relogio do beat (e sem o orfao (a), que fica para o beat).

    Cada tenant roda numa transacao curta; o WhatsApp e a escrita da cobranca
    ficam DEPOIS dela. Devolve contagens, para o log e os testes."""
    contagem = {"expirados": 0, "orfaos": 0, "pagas": 0, "canceladas": 0, "expiradas": 0}
    por_barbearia = defaultdict(list)
    abertas = Cobranca.objects.using(ALIAS).filter(
        motivo=MotivoCobranca.AGENDAMENTO, agendamento_id__isnull=False,
    )
    if barbearia_id is not None:
        abertas = abertas.filter(barbearia_id=barbearia_id)
    for c in abertas.filter(status=StatusCobranca.ABERTA):
        por_barbearia[c.barbearia_id].append(c)

    if barbearia_id is not None:
        alvos = {barbearia_id}
    else:
        # Os orfaos (a) nao deixam rastro em `Cobranca`: so' olhando cada tenant.
        alvos = set(Barbearia.objects.filter(ativo=True).values_list("id", flat=True))
        alvos |= set(por_barbearia)
    for bid in alvos:
        try:
            _varrer_barbearia(bid, por_barbearia.get(bid, []), agora, barbeiro_id, contagem)
        except Exception:
            # Uma barbearia com problema nao pode parar as outras.
            logger.exception("[pix] varredura da barbearia %s falhou", bid)
    return contagem


@contextmanager
def rodada_unica():
    """Trava consultiva do Postgres (`pg_try_advisory_lock`) para o beat: se a
    rodada anterior ainda esta rodando (passou de 60 s), esta pula em vez de se
    empilhar. Preferi isto a `expires` no beat porque `expires` so' descarta
    mensagem velha na fila, nao impede duas rodadas simultaneas; e a trava
    consultiva morre sozinha com a conexao se o processo cair. Sessao do alias
    `admin`, que a varredura nao usa em transacao longa. Entrega `True` se
    pegou a trava."""
    cur = connections[ALIAS].cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s)", [TRAVA_DA_VARREDURA])
    pegou = cur.fetchone()[0]
    try:
        yield pegou
    finally:
        if pegou:
            cur.execute("SELECT pg_advisory_unlock(%s)", [TRAVA_DA_VARREDURA])
        cur.close()


def _varrer_barbearia(bid, cobrancas, agora, barbeiro_id, contagem) -> None:
    ag = StatusAgendamento
    novo_estado = {}  # id da cobranca -> status que ela deve ter
    avisos = []
    with com_barbearia(bid):
        trancados = Agendamento.objects.select_for_update(of=("self",)).select_related(
            "cliente", "barbeiro",
        )
        ids = [c.agendamento_id for c in cobrancas]
        # So' os do barbeiro do pedido (no SQL: nao trancar o colega a toa) e
        # em ordem fixa, para duas varreduras nunca se esperarem em cruz.
        alvo = trancados.filter(id__in=ids)
        if barbeiro_id is not None:
            alvo = alvo.filter(barbeiro_id=barbeiro_id)
        por_id = {a.id: a for a in alvo.order_by("id")} if ids else {}
        for c in cobrancas:
            a = por_id.get(c.agendamento_id)
            if a is None:
                continue
            if a.status == ag.AGUARDANDO_PAGAMENTO:
                if c.status == StatusCobranca.ABERTA and c.expira_em is not None and c.expira_em <= agora:
                    Agendamento.objects.filter(id=a.id).update(status=ag.EXPIRADO)
                    novo_estado[c.id] = StatusCobranca.EXPIRADA
                    avisos.append((a, False))
                    contagem["expirados"] += 1
            elif a.status == ag.CONFIRMADO:
                # So' o "recebi" confirma um agendamento que tinha cobranca.
                novo_estado[c.id] = StatusCobranca.PAGA
            elif a.status == ag.EXPIRADO:
                if c.status == StatusCobranca.ABERTA:
                    novo_estado[c.id] = StatusCobranca.EXPIRADA
            else:  # CANCELADO_*
                if c.status == StatusCobranca.ABERTA:
                    novo_estado[c.id] = StatusCobranca.CANCELADA

        if barbeiro_id is None:
            # (a) AGUARDANDO sem cobranca aberta e mais velho que o prazo: o
            # processo morreu entre o commit do agendamento e a abertura da
            # cobranca (ou o proprio fallback falhou). Sem isto o horario
            # ficaria preso para sempre.
            com_aberta = Cobranca.objects.filter(
                status=StatusCobranca.ABERTA, agendamento_id__isnull=False,
            ).values("agendamento_id")
            limite = agora - timedelta(minutes=settings.PIX_AGENDAMENTO_PRAZO_MIN) - FOLGA_DO_ORFAO
            orfaos = list(
                Agendamento.objects.select_for_update(of=("self",))
                .select_related("cliente", "barbeiro")
                .filter(status=ag.AGUARDANDO_PAGAMENTO, criado_em__lte=limite)
                .exclude(id__in=com_aberta)
            )
            for a in orfaos:
                Agendamento.objects.filter(id=a.id).update(status=ag.EXPIRADO)
                avisos.append((a, True))
                contagem["orfaos"] += 1

            # Reparo guiado pelo AGENDAMENTO, de qualquer idade: CONFIRMADO com
            # cobranca ligada que nao esta paga so' acontece se o "recebi" (ou
            # um cancelamento de pago) parou entre os dois commits.
            pendente = Cobranca.objects.filter(
                agendamento_id=OuterRef("pk"),
                status__in=[StatusCobranca.ABERTA, StatusCobranca.EXPIRADA],
            )
            para_reparar = list(
                Agendamento.objects.select_for_update(of=("self",))
                .filter(status=ag.CONFIRMADO).filter(Exists(pendente))
                .order_by("id").values_list("id", flat=True)
            )
            if para_reparar:
                for cid in Cobranca.objects.filter(
                    agendamento_id__in=para_reparar,
                    status__in=[StatusCobranca.ABERTA, StatusCobranca.EXPIRADA],
                ).values_list("id", flat=True):
                    novo_estado[cid] = StatusCobranca.PAGA

    _gravar_cobrancas(novo_estado, agora, contagem)
    _avisar_expirados(bid, avisos)


def _gravar_cobrancas(novo_estado: dict, agora, contagem) -> None:
    """UPDATE condicional: so' o que ainda esta no estado de onde a varredura
    partiu. Se o "recebi" (ou outra varredura) chegou antes, nada muda."""
    por_destino = defaultdict(list)
    for cid, destino in novo_estado.items():
        por_destino[destino].append(cid)
    for destino, ids in por_destino.items():
        if destino == StatusCobranca.PAGA:
            partida = [StatusCobranca.ABERTA, StatusCobranca.EXPIRADA]
            extra = {"paga_em": agora, "como_foi_paga": ComoFoiPaga.MANUAL}
            chave = "pagas"
        else:
            partida = [StatusCobranca.ABERTA]
            extra = {}
            chave = "expiradas" if destino == StatusCobranca.EXPIRADA else "canceladas"
        n = Cobranca.objects.using(ALIAS).filter(id__in=ids, status__in=partida).update(
            status=destino, **extra,
        )
        contagem[chave] += n


def _avisar_expirados(bid, agendamentos) -> None:
    """Depois do commit, e fora de qualquer transacao: o cliente fica sabendo
    que o horario foi liberado. Falha de WhatsApp nao desfaz nada."""
    if not agendamentos:
        return
    barbearia = Barbearia.objects.get(id=bid)
    for a, orfao in agendamentos:
        if orfao:
            # Nunca houve Pix na tela: dizer "nao conseguimos confirmar seu Pix"
            # a quem nunca recebeu um seria estranho.
            texto = mensagens.msg_horario_liberado_sem_pix(
                barbearia_nome=barbearia.nome, inicio=a.inicio,
            )
        else:
            texto = mensagens.msg_pix_expirado(
                barbearia_nome=barbearia.nome, barbeiro_nome=a.barbeiro.nome,
                barbeiro_whatsapp=a.barbeiro.whatsapp, inicio=a.inicio,
            )
        transaction.on_commit(
            lambda a=a, texto=texto: _enviar_expirado(barbearia, a, texto)
        )


def _enviar_expirado(barbearia, a, texto) -> None:
    try:
        enviar_ao_cliente(
            barbearia, a.cliente.whatsapp, texto,
            tipo=TipoMensagem.CANCELAMENTO, cliente_nome=a.cliente.nome,
        )
    except Exception:
        logger.exception("[pix] aviso de Pix vencido nao saiu: agendamento %s", a.id)
