"""Clientes bloqueados (spec 2026-10-13): a equipe bloqueia quem marca e nao
aparece. O site recusa o numero, e qualquer aparelho que ja' marcou com ele,
sem dizer por que — a frase da recusa manda a pessoa chamar a barbearia.

O aparelho e' CONSULTADO, e nao copiado no bloqueio: assim pega tambem o
celular que marcou com o numero antes de ele ser bloqueado, e desbloquear e'
apagar um campo so'.
"""

from datetime import datetime

from django.utils import timezone

from tenant.models import Agendamento, Barbeiro, Cliente
from tenant.rls import com_barbearia

from . import pix_agendamento
from .agendamentos import AGUARDANDO, STATUS_CANCELAVEIS


def esta_bloqueado(
    barbearia_id, whatsapp: str, aparelho: str | None, marcado_por=None,
) -> bool:
    """`marcado_por`: o id do cliente bloqueado que a propria recusa deixou
    no navegador (cookie assinado, ver a view). Cobre quem marcou antes de
    a marca do aparelho existir: os agendamentos antigos tem `aparelho` nulo,
    e sem isto bastaria trocar de numero no mesmo celular."""
    with com_barbearia(barbearia_id):
        if Cliente.objects.filter(whatsapp=whatsapp, bloqueado_em__isnull=False).exists():
            return True
        if marcado_por and Cliente.objects.filter(
            id=marcado_por, bloqueado_em__isnull=False,
        ).exists():
            return True
        if not aparelho:
            return False
        return Agendamento.objects.filter(
            aparelho=aparelho, cliente__bloqueado_em__isnull=False,
        ).exists()


def id_do_bloqueado(barbearia_id, whatsapp: str):
    """O id do cliente bloqueado com este numero, ou None."""
    with com_barbearia(barbearia_id):
        return (
            Cliente.objects.filter(whatsapp=whatsapp, bloqueado_em__isnull=False)
            .values_list("id", flat=True)
            .first()
        )


def _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id):
    """O cliente do agendamento, ou None. Barbeiro comum so' alcanca os
    agendamentos dele — o do colega e' None (a rota responde 404, como o
    cancelar: 403 confirmaria que existe)."""
    a = Agendamento.objects.filter(id=agendamento_id).select_related("cliente").first()
    if a is None:
        return None
    if filtro_barbeiro_id and filtro_barbeiro_id != a.barbeiro_id:
        return None
    return a.cliente


def _futuros(cliente_id, agora: datetime):
    return Agendamento.objects.filter(
        cliente_id=cliente_id, status__in=STATUS_CANCELAVEIS, inicio__gt=agora,
    )


def previa(barbearia_id, agendamento_id, filtro_barbeiro_id, agora: datetime) -> dict | None:
    """O que a confirmacao do painel mostra antes de bloquear."""
    with com_barbearia(barbearia_id):
        c = _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id)
        if c is None:
            return None
        return {
            "clienteId": str(c.id), "nome": c.nome, "whatsapp": c.whatsapp,
            "horarios": _futuros(c.id, agora).count(),
            "bloqueado": c.bloqueado_em is not None,
        }


def bloquear(barbearia_id, agendamento_id, filtro_barbeiro_id, por_id, agora: datetime):
    """Marca o cliente e cancela os horarios futuros dele, com qualquer
    barbeiro, SEM mensagem (quem chama tambem nao manda). Devolve os
    cancelados `(barbeiro_id, agendamento_id, inicio)` para a rota refazer a
    lista do dia; `[]` se ja' estava bloqueado; None se nao achou.

    Ja' bloqueado nao cancela de novo: o que existe agora foi marcado pelo
    painel depois do bloqueio, e isso foi decisao de alguem da equipe."""
    with com_barbearia(barbearia_id):
        c = _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id)
        if c is None:
            return None
        if c.bloqueado_em is not None:
            return []
        Cliente.objects.filter(id=c.id).update(
            bloqueado_em=timezone.now(), bloqueado_por_id=por_id,
        )
        futuros = list(_futuros(c.id, agora).values_list("barbeiro_id", "id", "inicio", "status"))
        pagos = [
            {
                "cliente_nome": c.nome, "inicio": inicio, "valor_centavos": valor,
                "barbeiro_whatsapp": Barbeiro.objects.get(id=barbeiro_id).whatsapp,
            }
            for barbeiro_id, i, inicio, st in futuros
            if st == "CONFIRMADO" and (valor := pix_agendamento.valor_pago(i))
        ]
        _futuros(c.id, agora).update(status="CANCELADO_BARBEIRO", cancelado_em=timezone.now())
    # Quem esperava o Pix perde a cobranca junto, e nunca entrou na lista do
    # dia: so' os confirmados voltam para a rota refazer a lista.
    pix_agendamento.cancelar_abertas(i for _, i, _, st in futuros if st == AGUARDANDO)
    pix_agendamento.avisar_cancelamento_pago(barbearia_id, pagos, pelo_cliente=False)
    return [(b, i, ini) for b, i, ini, st in futuros if st != AGUARDANDO]


def listar(barbearia_id) -> list[dict]:
    with com_barbearia(barbearia_id):
        linhas = list(
            Cliente.objects.filter(bloqueado_em__isnull=False)
            .order_by("-bloqueado_em")
            .values("id", "nome", "whatsapp", "bloqueado_em", "bloqueado_por__nome")
        )
    return [
        {
            "id": str(l["id"]), "nome": l["nome"], "whatsapp": l["whatsapp"],
            "bloqueadoEm": l["bloqueado_em"], "bloqueadoPor": l["bloqueado_por__nome"],
        }
        for l in linhas
    ]


def desbloquear(barbearia_id, cliente_id) -> bool:
    """Os horarios cancelados no bloqueio NAO voltam."""
    with com_barbearia(barbearia_id):
        return bool(
            Cliente.objects.filter(id=cliente_id, bloqueado_em__isnull=False)
            .update(bloqueado_em=None, bloqueado_por=None)
        )
