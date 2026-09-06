import uuid

from tenant.datas import como_utc
from tenant.models import Bloqueio
from tenant.rls import com_barbearia


DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def folga_sobreposta(barbearia_id: str, barbeiro_id: str, campos: dict) -> str | None:
    """A recusa de empilhar folga em cima de folga, no mesmo dia e no mesmo
    barbeiro.

    Nada impedia isso, e o resultado aparecia na tela como "toda semana · seg,
    ter, ter, qua, qua, qua": o mesmo almoco gravado varias vezes. Para a
    AGENDA nao muda nada — dois bloqueios iguais fecham o mesmo buraco — mas
    sao linhas mortas que so' crescem, e a pessoa precisa apagar uma por uma.

    Encostar tambem conta: 12:00-13:00 e 12:30-13:30 na segunda nao sao duas
    pausas, e uma so' das 12:00 as 13:30 escrita de um jeito confuso.

    Ao contrario dos AGENDAMENTOS, aqui nao ha o que perguntar: ninguem esta
    esperando por um bloqueio, e a saida certa e' recusar e deixar a pessoa
    editar o que ja existe.
    """
    with com_barbearia(barbearia_id):
        existentes = list(Bloqueio.objects.filter(barbeiro_id=barbeiro_id))

    if campos["repete_semanalmente"]:
        dia, de, ate = campos["dia_semana"], campos["minutos_inicio"], campos["minutos_fim"]
        for b in existentes:
            if not b.repete_semanalmente or b.dia_semana != dia:
                continue
            if de < b.minutos_fim and b.minutos_inicio < ate:
                return (
                    f"Já tem {b.motivo.lower()} na {DIAS[dia]}, das "
                    f"{_hhmm(b.minutos_inicio)} às {_hhmm(b.minutos_fim)}. "
                    f"Apaga ou muda essa antes."
                )
        return None

    de, ate = campos["inicio"], campos["fim"]
    for b in existentes:
        if b.repete_semanalmente:
            continue
        if de < como_utc(b.fim) and como_utc(b.inicio) < ate:
            return "Já tem uma folga marcada nesse horário. Apaga ou muda essa antes."
    return None


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
