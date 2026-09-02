import uuid

from tenant.models import Barbeiro, Bloqueio, HorarioTrabalho
from django.utils import timezone

from tenant.rls import com_barbearia

MINUTOS_DIA = 24 * 60


def _inteiro_no_dia(m) -> bool:
    """Espelha `Number.isInteger(m) && m >= 0 && m <= MINUTOS_DIA` do JS: la
    todo numero e' float por baixo, e `Number.isInteger` confere o VALOR, nao
    o tipo. `isinstance(m, int)` sozinho rejeitaria um `540.0` vindo do JSON
    que em JS passaria — por isso a checagem e' pelo valor."""
    if isinstance(m, bool) or not isinstance(m, (int, float)):
        return False
    return float(m).is_integer() and 0 <= m <= MINUTOS_DIA


def jornada_valida(dia_semana, minutos_inicio, minutos_fim) -> str | None:
    """Porte de `jornadaValida` (front/src/lib/horarios.ts). Protege o motor
    de horarios, que confia no que esta gravado."""
    if isinstance(dia_semana, bool) or not isinstance(dia_semana, int):
        return "Dia da semana inválido."
    if dia_semana < 0 or dia_semana > 6:
        return "Dia da semana inválido."
    if not _inteiro_no_dia(minutos_inicio) or not _inteiro_no_dia(minutos_fim):
        return "Horário fora do dia."
    # Igual tambem e' recusado: jornada de duracao zero nao e' "fechado", e'
    # uma linha que o motor le e da qual nao sai slot nenhum — fechar e'
    # APAGAR a linha, e ter duas representacoes do mesmo estado confunde.
    if minutos_inicio >= minutos_fim:
        return "A hora de fim tem que ser depois da de início."
    return None


def bloqueio_valido(
    *, repete_semanalmente: bool, dia_semana, minutos_inicio, minutos_fim, inicio, fim,
) -> str | None:
    """Porte de `bloqueioValido`. Semanal e pontual sao mutuamente
    exclusivos: o motor le um formato OU o outro, e aceitar os dois juntos
    gravaria uma linha cuja interpretacao depende de qual campo alguem leu
    primeiro."""
    tem_semanal = dia_semana is not None or minutos_inicio is not None or minutos_fim is not None
    tem_pontual = inicio is not None or fim is not None

    if tem_semanal and tem_pontual:
        return "Escolhe: toda semana ou uma vez só."

    if repete_semanalmente:
        if dia_semana is None or minutos_inicio is None or minutos_fim is None:
            return "Bloqueio de toda semana precisa de dia, hora de início e de fim."
        return jornada_valida(dia_semana, minutos_inicio, minutos_fim)

    if inicio is None or fim is None:
        return "Bloqueio de uma vez precisa de começo e fim."
    if fim <= inicio:
        return "O fim tem que ser depois do começo."
    return None


def listar_expediente(barbearia_id: str, barbeiro_id: str, agora=None) -> dict:
    """Os SETE dias sempre, com minutos nulos onde esta fechado — a tela
    precisa desenhar a semana inteira, e 'nao veio na lista' e' ambiguo com
    'nao carregou'."""
    with com_barbearia(barbearia_id):
        horarios = list(
            HorarioTrabalho.objects.filter(barbeiro_id=barbeiro_id).values(
                "dia_semana", "minutos_inicio", "minutos_fim"
            )
        )
        # A folga de UMA VEZ que ja terminou sai da lista: ela era um evento,
        # e depois de passar nao diz mais nada sobre a agenda — so' empurra
        # para baixo as que ainda valem. A semanal nao entra nesse filtro
        # porque ela se repete: `fim` nem existe nela.
        #
        # Filtro de LEITURA, nao apagamento: o registro continua no banco, que
        # e' o que mantem o historico honesto quando alguem for entender por
        # que a agenda estava fechada naquela terca.
        bloqueios = list(
            Bloqueio.objects.filter(barbeiro_id=barbeiro_id)
            .exclude(repete_semanalmente=False, fim__lte=agora or timezone.now())
            .order_by("-repete_semanalmente", "criado_em")
            .values(
                "id", "motivo", "observacao", "repete_semanalmente", "dia_semana",
                "minutos_inicio", "minutos_fim", "inicio", "fim",
            )
        )

    por_dia = {h["dia_semana"]: h for h in horarios}
    expediente = [
        por_dia.get(d, {"dia_semana": d, "minutos_inicio": None, "minutos_fim": None})
        for d in range(7)
    ]
    return {"expediente": expediente, "bloqueios": bloqueios}


def definir_horario(
    barbearia_id: str, barbeiro_id: str, dia_semana: int, minutos_inicio, minutos_fim,
) -> None:
    with com_barbearia(barbearia_id):
        # O barbeiro pode nao ser deste tenant: o RLS nao deixaria a criacao
        # passar, mas a mensagem sairia como erro de banco. Conferir antes
        # deixa a resposta honesta — e' o mesmo `existe` do route.ts, que
        # devolve `ok: true` calado quando o id nao bate (nunca deveria
        # acontecer, ja que o alvo vem da propria sessao).
        if not Barbeiro.objects.filter(id=barbeiro_id).exists():
            return

        atualizados = HorarioTrabalho.objects.filter(
            barbeiro_id=barbeiro_id, dia_semana=dia_semana
        ).update(minutos_inicio=minutos_inicio, minutos_fim=minutos_fim)
        if atualizados == 0:
            HorarioTrabalho.objects.create(
                id=str(uuid.uuid4()), barbearia_id=barbearia_id, barbeiro_id=barbeiro_id,
                dia_semana=dia_semana, minutos_inicio=minutos_inicio, minutos_fim=minutos_fim,
            )


def apagar_horario(barbearia_id: str, barbeiro_id: str, dia_semana: int) -> None:
    """Fechar um dia e' APAGAR a linha: sem `HorarioTrabalho` naquele dia, o
    motor devolve vazio na primeira linha. A ausencia ja e' a representacao
    de 'nao trabalho'."""
    with com_barbearia(barbearia_id):
        HorarioTrabalho.objects.filter(barbeiro_id=barbeiro_id, dia_semana=dia_semana).delete()
