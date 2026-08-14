from dataclasses import dataclass
from datetime import datetime, timedelta

from tenant.config import ANTECEDENCIA_MINIMA_MIN, GRANULARIDADE_MIN
from tenant.datas import como_utc, dia_semana_de, local_para_utc

# O MOTOR, e ele e PURO: nao conhece Django, nao consulta banco e nao sabe o
# que e um `Servico`. Recebe listas e devolve listas.
#
# Isso nao e estilo. E o que permite testar "das 9h as 18h, com almoco das 12h
# as 13h e um corte marcado as 15h, quais horarios sobram" sem montar cenario
# nenhum — e e por isso que a regra de colisao pode ser exercitada nos casos de
# borda, que sao onde ela erra.


@dataclass(frozen=True)
class Slot:
    inicio: datetime
    fim: datetime
    barbeiro_id: str


def colide(a_ini, a_fim, b_ini, b_fim) -> bool:
    """Intervalos SEMIABERTOS [inicio, fim): quem termina 16:40 nao colide com
    quem comeca 16:40.

    Trocar qualquer um dos dois `<` por `<=` faz a agenda perder um horario a
    cada agendamento existente — e o sintoma e "sumiu um horario", nunca "a
    comparacao esta errada".
    """
    return a_ini < b_fim and a_fim > b_ini


def bloqueios_do_dia(bloqueios, dia: str, dia_semana: int) -> list[tuple]:
    """As duas formas de bloqueio traduzidas para instantes do dia pedido.

    O semanal vira hora daquela data; o pontual entra so se ENCOSTAR no dia.
    Descartar o pontual de outra data nao muda o que o motor decide (ele nao
    colidiria mesmo) — e o que faz esta lista servir tambem para DESENHAR o
    dia, que e o que o quadro do painel vai precisar. Uma segunda copia desta
    traducao seria uma segunda regra de recorrencia, e a que diverge e sempre
    a que ninguem esta olhando.
    """
    abre = local_para_utc(dia, 0)
    fecha = local_para_utc(dia, 24 * 60)

    faixas = []
    for b in bloqueios:
        if b.repete_semanalmente:
            if b.dia_semana != dia_semana:
                continue
            faixas.append(
                (local_para_utc(dia, b.minutos_inicio), local_para_utc(dia, b.minutos_fim))
            )
            continue

        inicio, fim = como_utc(b.inicio), como_utc(b.fim)
        if colide(inicio, fim, abre, fecha):
            faixas.append((inicio, fim))
    return faixas


def slots_livres(
    *,
    barbeiro_id: str,
    duracao_min: int,
    expediente,
    bloqueios,
    agendamentos,
    dia: str,
    agora: datetime,
) -> list[Slot]:
    """Os horarios livres de UM barbeiro num dia.

    `agora` e INJETADO, nunca lido aqui dentro. Com um relogio interno, todo
    teste de "esse horario ja passou" viraria refem da hora em que a suite
    roda — passaria de manha e falharia a tarde.

    O passo da grade e `GRANULARIDADE_MIN` e NAO a duracao do servico: um
    corte de 40 minutos comeca de 30 em 30. A condicao de parada e
    `m + duracao <= fim`, o que impede oferecer um horario que estoura o
    expediente — o cliente marcaria as 17:40 um corte de 40 min num expediente
    que fecha as 18h.
    """
    semana = dia_semana_de(dia)
    jornada = next((h for h in expediente if h.dia_semana == semana), None)
    if jornada is None:
        # O barbeiro nao declarou expediente nesse dia. Nao e erro: e fechado.
        return []

    limite = agora + timedelta(minutes=ANTECEDENCIA_MINIMA_MIN)
    bloqueados = bloqueios_do_dia(bloqueios, dia, semana)
    ocupados = [(como_utc(a.inicio), como_utc(a.fim)) for a in agendamentos]

    livres = []
    m = jornada.minutos_inicio
    while m + duracao_min <= jornada.minutos_fim:
        inicio = local_para_utc(dia, m)
        fim = inicio + timedelta(minutes=duracao_min)
        m += GRANULARIDADE_MIN

        if inicio < limite:
            continue
        if any(colide(inicio, fim, bi, bf) for bi, bf in bloqueados):
            continue
        if any(colide(inicio, fim, ai, af) for ai, af in ocupados):
            continue

        livres.append(Slot(inicio=inicio, fim=fim, barbeiro_id=barbeiro_id))
    return livres


def unir_slots(listas, ordem_por_barbeiro: dict) -> list[Slot]:
    """"Tanto faz": junta os slots de varios barbeiros numa lista so.

    O mesmo instante em dois barbeiros vira UM slot, do de menor `ordem`. Nao
    e detalhe de apresentacao: e o desempate que decide quem recebe o cliente
    que nao escolheu ninguem, e ele tem que ser estavel. Sem criterio, a mesma
    tela recarregada duas vezes ofereceria barbeiros diferentes para o mesmo
    horario, e o cliente veria o nome mudar debaixo do dedo.

    Barbeiro sem `ordem` no mapa perde qualquer desempate (vai para o fim) em
    vez de estourar — o mapa vem da mesma consulta que gerou os slots, entao a
    ausencia nao acontece, mas nao vale trocar um horario oferecido por um
    KeyError.
    """
    por_instante: dict[datetime, Slot] = {}
    for slot in (s for lista in listas for s in lista):
        atual = por_instante.get(slot.inicio)
        if atual is None:
            por_instante[slot.inicio] = slot
            continue
        novo = ordem_por_barbeiro.get(slot.barbeiro_id, float("inf"))
        velho = ordem_por_barbeiro.get(atual.barbeiro_id, float("inf"))
        if novo < velho:
            por_instante[slot.inicio] = slot

    return sorted(por_instante.values(), key=lambda s: s.inicio)
