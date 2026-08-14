from django.db.models import Min

from tenant.models import BarbeiroServico
from tenant.rls import com_barbearia

QUALQUER = "qualquer"


def listar_para_agendamento(barbearia_id: str, barbeiro_id: str = QUALQUER) -> list[dict]:
    """O que o cliente pode escolher, e a duracao que a tela vai mostrar.

    A lista sai dos VINCULOS, nunca da tabela `Servico` direto. Um servico que
    existe na barbearia mas nao esta ligado a ninguem nao pode aparecer: quem o
    escolhesse cairia numa tela de horarios vazia, sem erro nenhum. E o mesmo
    beco sem saida que a lista de barbeiros evita do outro lado.

    Tres condicoes, e as tres tem que valer juntas: o vinculo ativo, o barbeiro
    ativo e o servico ativo. Esquecer qualquer uma poe na tela uma opcao que
    nao leva a lugar nenhum.

    `barbeiro_id="qualquer"` e o caso comum — o cliente escolhe o servico ANTES
    do barbeiro. Ai a duracao mostrada e a MENOR entre os barbeiros que fazem
    aquele servico, e isso e uma decisao de produto, nao um detalhe: o barbeiro
    so e resolvido na escolha do horario, entao prometer a duracao maior faria
    a tela de horarios oferecer MENOS vagas do que existem de verdade. Mostrar
    a menor e a promessa que o passo seguinte consegue cumprir.

    O `Min` roda no banco, num GROUP BY, e nao num laco em Python. Nao e so
    velocidade: o laco equivalente do route.ts precisa de um Map intermediario
    e de uma comparacao escrita a mao, e e ali que a regra "a menor" pode virar
    "a ultima" numa refatoracao distraida.
    """
    with com_barbearia(barbearia_id):
        vinculos = BarbeiroServico.objects.filter(
            ativo=True, barbeiro__ativo=True, servico__ativo=True
        )
        if barbeiro_id != QUALQUER:
            vinculos = vinculos.filter(barbeiro_id=barbeiro_id)

        return list(
            vinculos.values("servico_id", "servico__nome", "servico__ordem")
            # Alias `duracao` e nao `duracao_min`: o Django recusa uma anotacao
            # com o mesmo nome de um campo do model ("conflicts with a field").
            .annotate(duracao=Min("duracao_min"))
            # `servico__nome` como desempate NAO existe no route.ts, e entra de
            # proposito: la a ordem de dois servicos com a mesma `ordem` sai da
            # ordem de insercao num Map, que vem de um `findMany` sem
            # `orderBy` — ou seja, indefinida. Empate acontece (nada impede
            # duas linhas com ordem 0), e uma lista que troca de ordem sozinha
            # entre dois carregamentos e o tipo de coisa que se atribui ao
            # navegador. Desempatar por nome nao muda nenhum caso ordenado.
            .order_by("servico__ordem", "servico__nome")
        )
