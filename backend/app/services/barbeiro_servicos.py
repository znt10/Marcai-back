from tenant.models import BarbeiroServico, Servico
from tenant.rls import com_barbearia

from .servicos import ErroDuracao, validar_duracao


def listar_vinculos(barbearia_id: str, barbeiro_id: str) -> list[dict]:
    """Todos os servicos ATIVOS, marcados ou nao: a tela e' uma lista de
    caixas, e "nao veio" seria ambiguo com "nao faz". Porte de
    `GET /painel/barbeiro-servicos`."""
    with com_barbearia(barbearia_id):
        servicos = list(
            Servico.objects.filter(ativo=True)
            .order_by("ordem")
            .values("id", "nome", "duracao_minima_min", "duracao_sugerida_min")
        )
        ligados = {
            v["servico_id"]: v
            for v in BarbeiroServico.objects.filter(barbeiro_id=barbeiro_id).values(
                "servico_id", "duracao_min", "ativo"
            )
        }

    saida = []
    for s in servicos:
        v = ligados.get(s["id"])
        saida.append(
            {
                "servico_id": s["id"],
                "nome": s["nome"],
                "duracao_minima_min": s["duracao_minima_min"],
                "faz": v["ativo"] if v else False,
                # Sem vinculo, mostra a sugerida — e' o que entraria ao marcar.
                "duracao_min": v["duracao_min"] if v else s["duracao_sugerida_min"],
            }
        )
    return saida


def definir_vinculo(
    barbearia_id: str, barbeiro_id: str, servico_id: str, faz: bool, duracao_min: int | None,
) -> dict:
    with com_barbearia(barbearia_id):
        servico = Servico.objects.filter(id=servico_id).values(
            "duracao_minima_min", "duracao_sugerida_min"
        ).first()
        if servico is None:
            return {"tipo": "nao_encontrado"}

        existente = BarbeiroServico.objects.filter(
            barbeiro_id=barbeiro_id, servico_id=servico_id
        ).values("duracao_min").first()

        # A duracao so e' decidida aqui: o pedido manda, senao a praticada,
        # senao a sugerida do servico.
        duracao = duracao_min
        if duracao is None:
            duracao = existente["duracao_min"] if existente else servico["duracao_sugerida_min"]

        try:
            validar_duracao(duracao, servico["duracao_minima_min"])
        except ErroDuracao as e:
            return {"tipo": "recusado", "erro": str(e)}

        # NUNCA `.get()`/`.save()` num BarbeiroServico — o docstring do model
        # explica: a pk declarada e' so `barbeiro`, e um `.save()` gravaria
        # pela pk sozinha, achando um vinculo arbitrario quando o mesmo
        # barbeiro tem mais de um servico. Filtrar (e atualizar) pelos DOIS
        # campos, sempre — e' por isso que isto NAO usa `update_or_create`.
        atualizados = BarbeiroServico.objects.filter(
            barbeiro_id=barbeiro_id, servico_id=servico_id
        ).update(duracao_min=duracao, ativo=faz)
        if atualizados == 0:
            # Desmarcar e' `ativo=False`, nunca DELETE: a linha guarda a
            # duracao que aquele barbeiro praticava, e remarcar devolve o
            # numero em vez de voltar ao sugerido.
            BarbeiroServico.objects.create(
                barbeiro_id=barbeiro_id, servico_id=servico_id,
                barbearia_id=barbearia_id, duracao_min=duracao, ativo=faz,
            )
        return {"tipo": "ok"}
