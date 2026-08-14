from tenant.models import Barbeiro, BarbeiroServico
from tenant.rls import com_barbearia


def listar_para_agendamento(barbearia_id: str) -> list[dict]:
    """Quem o CLIENTE pode escolher, e a regra nao e "todos os ativos".

    Duas condicoes, e a segunda tem duas metades que ja custaram um bug do
    lado TypeScript (front/src/app/api/barbeiros/route.ts):

    1. o barbeiro esta ativo;
    2. ele tem ao menos um vinculo ATIVO cujo servico tambem esta ATIVO.

    A metade que falta com facilidade e a do servico. Com o vinculo ativo e o
    servico desativado na barbearia inteira, o barbeiro continuava na lista e
    a tela seguinte abria vazia — beco sem saida, sem erro nenhum. Aparecer na
    lista e nao ter o que agendar e pior que nao aparecer.

    O `com_barbearia` embrulha as DUAS consultas porque a subconsulta e
    resolvida no banco, dentro da mesma transacao: as politicas de RLS filtram
    `Barbeiro`, `BarbeiroServico` e `Servico` pelo mesmo `app.barbearia_id`,
    entao nao ha `filter(barbearia_id=...)` escrito aqui — e nao deve haver. O
    dia em que alguem acrescentar um por seguranca e o dia em que passa a
    existir um segundo lugar que decide tenant, e os dois vao divergir.
    """
    with com_barbearia(barbearia_id):
        vinculados = BarbeiroServico.objects.filter(
            ativo=True, servico__ativo=True
        ).values("barbeiro_id")

        return list(
            Barbeiro.objects.filter(ativo=True, id__in=vinculados)
            .order_by("ordem")
            .values("id", "nome", "foto_url")
        )
