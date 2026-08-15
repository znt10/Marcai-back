import uuid

from tenant.models import Bloqueio
from tenant.rls import com_barbearia


def criar_bloqueio(barbearia_id: str, barbeiro_id: str, campos: dict) -> str:
    with com_barbearia(barbearia_id):
        novo_id = str(uuid.uuid4())
        Bloqueio.objects.create(
            id=novo_id, barbearia_id=barbearia_id, barbeiro_id=barbeiro_id, **campos,
        )
    return novo_id


def apagar_bloqueio(barbearia_id: str, bloqueio_id: str, filtro_barbeiro_id: str | None) -> bool:
    """`filtro_barbeiro_id` e' o `filtroDoBarbeiro` ja resolvido: None para o
    dono (mexe em qualquer um), o id do proprio barbeiro caso contrario.

    A reconferencia acontece DEPOIS de carregar, como no cancelamento de
    agendamento: um barbeiro que forje o id do bloqueio de um colega recebe
    404, nunca 403 — 403 confirmaria que o registro existe."""
    with com_barbearia(barbearia_id):
        bloqueio = Bloqueio.objects.filter(id=bloqueio_id).values("barbeiro_id").first()
        if bloqueio is None:
            return False
        if filtro_barbeiro_id and filtro_barbeiro_id != bloqueio["barbeiro_id"]:
            return False

        Bloqueio.objects.filter(id=bloqueio_id).delete()
        return True
