import uuid

from django.db.models import Count, Min, Q

from tenant.config import DURACAO_MAXIMA_MIN, DURACAO_MINIMA_MIN
from tenant.models import BarbeiroServico, Servico
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
            #
            # `preco` pelo mesmo `Min`, e pelo mesmo motivo de produto: o
            # cliente ainda nao escolheu barbeiro, entao o menor preco e' a
            # promessa que a escolha seguinte consegue cumprir. `Min` ignora
            # NULL sozinho — um barbeiro sem preco definido nao participa da
            # conta, e se NINGUEM tiver preco o resultado e' None (a tela nao
            # mostra preco nenhum pra aquele servico).
            .annotate(duracao=Min("duracao_min"), preco=Min("preco_centavos"))
            # `servico__nome` como desempate NAO existe no route.ts, e entra de
            # proposito: la a ordem de dois servicos com a mesma `ordem` sai da
            # ordem de insercao num Map, que vem de um `findMany` sem
            # `orderBy` — ou seja, indefinida. Empate acontece (nada impede
            # duas linhas com ordem 0), e uma lista que troca de ordem sozinha
            # entre dois carregamentos e o tipo de coisa que se atribui ao
            # navegador. Desempatar por nome nao muda nenhum caso ordenado.
            .order_by("servico__ordem", "servico__nome")
        )


# ---------------------------------------------------------------- painel


class ErroDuracao(Exception):
    """Porte de `ErroDuracao` (front/src/lib/servicos.ts). A mensagem VAI para
    a tela — e' `str(e)`, nao um codigo — entao cada `raise` carrega o texto
    final."""


def validar_duracao(duracao_min: int, servico_duracao_minima_min: int) -> None:
    """Confere os TRES limites, inclusive os dois que o CHECK do banco ja
    cobre. Redundante de proposito: a mensagem daqui e' legivel na tela; a do
    CHECK e' um despejo do Postgres."""
    if not isinstance(duracao_min, int) or isinstance(duracao_min, bool):
        raise ErroDuracao("A duração precisa ser um número inteiro de minutos.")
    if duracao_min < DURACAO_MINIMA_MIN:
        raise ErroDuracao(f"A duração precisa ser de pelo menos {DURACAO_MINIMA_MIN} minutos.")
    if duracao_min > DURACAO_MAXIMA_MIN:
        raise ErroDuracao(f"A duração pode ser de no máximo {DURACAO_MAXIMA_MIN} minutos.")
    if duracao_min < servico_duracao_minima_min:
        raise ErroDuracao(f"Esse serviço precisa de pelo menos {servico_duracao_minima_min} minutos.")


class ErroPreco(Exception):
    """Mesmo estilo de `ErroDuracao`: a mensagem VAI pra tela, redundante de
    proposito com o CHECK do banco (`barbeiro_servico_preco_valido`) — aqui
    a mensagem e' legivel, a do CHECK e' um despejo do Postgres."""


def validar_preco(preco_centavos: int | None) -> None:
    """`None` e' um valor VALIDO — o barbeiro ainda nao decidiu, e marcar nao
    pode passar a exigir preco. So recusa quando ALGUEM tentou um preco que
    nao faz sentido: nao-inteiro, ou <= 0."""
    if preco_centavos is None:
        return
    if not isinstance(preco_centavos, int) or isinstance(preco_centavos, bool):
        raise ErroPreco("O preço precisa ser um número inteiro de centavos.")
    if preco_centavos <= 0:
        raise ErroPreco("O preço precisa ser maior que zero.")


def limites_do_servico(duracao_minima_min: int, duracao_sugerida_min: int) -> str | None:
    """Os TRES limites do catalogo: os dois globais e a relacao entre as duas
    duracoes do proprio servico. Porte de `limitesDoServico`."""
    if duracao_minima_min < DURACAO_MINIMA_MIN or duracao_sugerida_min < DURACAO_MINIMA_MIN:
        return f"O mínimo é {DURACAO_MINIMA_MIN} minutos."
    if duracao_minima_min > DURACAO_MAXIMA_MIN or duracao_sugerida_min > DURACAO_MAXIMA_MIN:
        return f"O máximo é {DURACAO_MAXIMA_MIN} minutos."
    # A sugerida e' o que entra no vinculo ao marcar; menor que a minima
    # criaria um vinculo que `validar_duracao` recusaria logo depois.
    if duracao_minima_min > duracao_sugerida_min:
        return "A duração sugerida não pode ser menor que a mínima."
    return None


def listar_para_painel(barbearia_id: str) -> list[dict]:
    """O catalogo inteiro (ativo e inativo), com quantos barbeiros ATIVOS
    oferecem cada um — zero e' o aviso de que o servico existe e ninguem faz.
    """
    with com_barbearia(barbearia_id):
        return list(
            Servico.objects.annotate(
                barbeiros=Count(
                    "vinculos",
                    filter=Q(vinculos__ativo=True, vinculos__barbeiro__ativo=True),
                )
            )
            .order_by("-ativo", "ordem")
            .values(
                "id", "nome", "ativo", "ordem",
                "duracao_minima_min", "duracao_sugerida_min", "barbeiros",
            )
        )


def criar(barbearia_id: str, nome: str, duracao_minima_min: int, duracao_sugerida_min: int) -> dict:
    """Cria o servico, ou devolve `repetido` se o nome ja existe (ativo ou
    nao) — o indice unico e' `[barbeariaId, nome]` e nao distingue
    desativado, entao esta checagem e' o que evita um 500 do Postgres."""
    with com_barbearia(barbearia_id):
        existente = Servico.objects.filter(nome=nome).values("ativo").first()
        if existente:
            return {"tipo": "repetido", "ativo": existente["ativo"]}

        ultimo = Servico.objects.order_by("-ordem").values("ordem").first()
        novo_id = str(uuid.uuid4())
        Servico.objects.create(
            id=novo_id, barbearia_id=barbearia_id, nome=nome,
            duracao_minima_min=duracao_minima_min,
            duracao_sugerida_min=duracao_sugerida_min,
            ordem=(ultimo["ordem"] if ultimo else -1) + 1,
        )
        return {"tipo": "ok", "id": novo_id}


def atualizar(barbearia_id: str, servico_id: str, campos: dict) -> dict:
    """`campos` ja chega em nomes de coluna Django (snake_case), so com o que
    mudou. Os limites sao conferidos contra o estado FINAL (o que veio
    mesclado com o que ja estava): subir a minima sem mexer na sugerida pode
    inverter as duas."""
    with com_barbearia(barbearia_id):
        atual = Servico.objects.filter(id=servico_id).values(
            "nome", "duracao_minima_min", "duracao_sugerida_min"
        ).first()
        if atual is None:
            return {"tipo": "nao_encontrado"}

        duracao_minima_min = campos.get("duracao_minima_min", atual["duracao_minima_min"])
        duracao_sugerida_min = campos.get("duracao_sugerida_min", atual["duracao_sugerida_min"])
        recusa = limites_do_servico(duracao_minima_min, duracao_sugerida_min)
        if recusa:
            return {"tipo": "recusado", "erro": recusa, "status": 422}

        novo_nome = campos.get("nome")
        if novo_nome is not None and novo_nome != atual["nome"]:
            if Servico.objects.filter(nome=novo_nome).exists():
                return {
                    "tipo": "recusado",
                    "erro": "Já existe um serviço com esse nome.",
                    "status": 409,
                }

        # Desativar NAO mexe em agendamento: eles guardam `servico_nome`
        # copiado no momento da marcacao, para o historico nao depender do
        # catalogo de hoje.
        Servico.objects.filter(id=servico_id).update(**campos)
        return {"tipo": "ok"}
