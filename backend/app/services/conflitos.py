from datetime import datetime

from tenant.datas import (
    como_utc,
    dia_semana_de,
    formatar_instante_iso,
    local_para_utc,
    utc_para_local,
)
from tenant.models import Agendamento, Bloqueio, HorarioTrabalho
from tenant.rls import com_barbearia

from .slots import colide


def _dentro_de_algum_bloqueio(a_inicio, a_fim, bloqueios, dia: str, dia_semana: int) -> bool:
    for b in bloqueios:
        if b.repete_semanalmente:
            if b.dia_semana != dia_semana:
                continue
            if colide(
                a_inicio, a_fim,
                local_para_utc(dia, b.minutos_inicio), local_para_utc(dia, b.minutos_fim),
            ):
                return True
        elif colide(a_inicio, a_fim, como_utc(b.inicio), como_utc(b.fim)):
            return True
    return False


def listar_conflitos(barbearia_id: str, barbeiro_id: str, agora: datetime) -> list[dict]:
    """O que ficou pendurado depois de encurtar o expediente ou marcar
    folga por cima de horario ja vendido. Encurtar e' PERMITIDO — fechar a
    agenda e' o que se faz agora, com o braco quebrado, e recusar deixaria o
    cliente batendo numa porta fechada. O sistema so mostra o que sobrou."""
    with com_barbearia(barbearia_id):
        agendamentos = list(
            Agendamento.objects.filter(
                barbeiro_id=barbeiro_id, status="CONFIRMADO", inicio__gt=agora,
            )
            .select_related("cliente")
            .order_by("inicio")
        )
        expediente = list(HorarioTrabalho.objects.filter(barbeiro_id=barbeiro_id))
        bloqueios = list(Bloqueio.objects.filter(barbeiro_id=barbeiro_id))

    saida = []
    for a in agendamentos:
        # `como_utc` uma vez por agendamento: a coluna e' `timestamp WITHOUT
        # time zone`, e comparar o valor cru (naive) contra `abre`/`fecha`
        # (aware, de `local_para_utc`) estoura em Python — o filtro por
        # queryset acima vai bem porque ali quem compara e' o Postgres.
        inicio, fim = como_utc(a.inicio), como_utc(a.fim)
        dia, _ = utc_para_local(inicio)
        dia_semana = dia_semana_de(dia)
        jornada = next((h for h in expediente if h.dia_semana == dia_semana), None)

        # Fora da jornada — inclusive quando o dia foi fechado e nao ha
        # jornada nenhuma.
        em_conflito = jornada is None
        if jornada is not None:
            abre = local_para_utc(dia, jornada.minutos_inicio)
            fecha = local_para_utc(dia, jornada.minutos_fim)
            if inicio < abre or fim > fecha:
                em_conflito = True
            else:
                em_conflito = _dentro_de_algum_bloqueio(inicio, fim, bloqueios, dia, dia_semana)

        if em_conflito:
            saida.append(
                {
                    "id": a.id,
                    "inicio": formatar_instante_iso(inicio),
                    "fim": formatar_instante_iso(fim),
                    "servicoNome": a.servico_nome,
                    "clienteNome": a.cliente.nome,
                    "clienteWhatsapp": a.cliente.whatsapp,
                }
            )
    return saida
