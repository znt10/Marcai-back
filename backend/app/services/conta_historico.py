"""O historico da conta: um bloco por estabelecimento onde o numero dela ja
tem cadastro, e o cancelamento logado.

A conta e' global, o agendamento e' do tenant. A ponte e' a funcao SQL
`barbearias_do_whatsapp` (so' ids), e cada leitura de agendamento acontece
dentro de `com_barbearia(id)` — um bloco durable por estabelecimento, nunca
aninhado, e o RLS segue valendo em cada um."""
import uuid
from datetime import datetime

from django.db import connection

from tenant.config import CONTA_HISTORICO_POR_LUGAR
from tenant.datas import formatar_instante_iso
from tenant.models import Agendamento, Barbearia
from tenant.rls import com_barbearia
from tenant.telefone import formas_gravadas

from .agendamentos import pode_cancelar


def barbearias_da_conta(conta) -> list[str]:
    """Os ids onde algum `Cliente` tem o numero da conta (em qualquer das
    formas gravadas). Roda na conexao padrao, sem tenant: a funcao e' SECURITY
    DEFINER e devolve so' ids."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT barbearias_do_whatsapp(%s::text[])", [formas_gravadas(conta.whatsapp)],
        )
        return [str(linha[0]) for linha in cur.fetchall()]


def _agendamentos_do_lugar(barbearia_id, formas: list[str], agora: datetime) -> list[dict]:
    with com_barbearia(barbearia_id):
        linhas = list(
            Agendamento.objects.filter(cliente__whatsapp__in=formas)
            .select_related("barbeiro")
            .order_by("-inicio")[:CONTA_HISTORICO_POR_LUGAR]
        )
        return [
            {
                "codigo": a.codigo,
                "servicoNome": a.servico_nome,
                "barbeiroNome": a.barbeiro.nome,
                "inicio": formatar_instante_iso(a.inicio),
                "status": a.status,
                "podeCancelar": pode_cancelar(a, agora),
                "_inicio": a.inicio,
            }
            for a in linhas
        ]


def historico(conta, barbearia_atual_id, agora: datetime) -> list[dict]:
    formas = formas_gravadas(conta.whatsapp)
    ids = barbearias_da_conta(conta)
    # `Barbearia` fica fora do RLS. Inativa some: a conta nao enxerga (nem
    # cancela em) um estabelecimento desligado.
    lugares = list(Barbearia.objects.filter(id__in=ids, ativo=True))

    itens = []
    for b in lugares:
        linhas = _agendamentos_do_lugar(b.id, formas, agora)
        itens.append((b, linhas))

    atual = str(barbearia_atual_id)
    # A atual primeiro; as outras pelo agendamento mais recente (sem nenhum, por ultimo).
    itens.sort(key=lambda p: (
        str(p[0].id) != atual,
        -p[1][0]["_inicio"].timestamp() if p[1] else float("inf"),
    ))
    return [
        {
            "barbeariaId": str(b.id), "slug": b.slug, "nome": b.nome, "tipo": b.tipo,
            "agendamentos": [{k: v for k, v in ag.items() if k != "_inicio"} for ag in linhas],
        }
        for b, linhas in itens
    ]


def barbearia_ativa_da_conta(conta, barbearia_id) -> Barbearia | None:
    """A barbearia para cancelar logado, ou `None` (vira 404): id malformado,
    fora das barbearias da conta, ou inativa."""
    try:
        alvo = uuid.UUID(str(barbearia_id))
    except (ValueError, AttributeError, TypeError):
        return None
    if str(alvo) not in barbearias_da_conta(conta):
        return None
    return Barbearia.objects.filter(id=alvo, ativo=True).first()
