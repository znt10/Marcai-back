"""O motor de horarios, testado SEM banco.

Nenhum teste aqui usa `django_db`: `slots_livres` recebe listas e devolve
listas. E o que permite exercitar as bordas — o horario que encosta no
bloqueio, o que estoura o expediente, o que ja passou — sem montar cenario, e
por isso elas estao cobertas de verdade.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.slots import bloqueios_do_dia, colide, slots_livres, unir_slots
from tenant.datas import dia_semana_de, local_para_utc

DIA = "2026-08-12"  # uma quarta-feira
ONTEM = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _jornada(inicio=9 * 60, fim=18 * 60, dia_semana=None):
    return SimpleNamespace(
        dia_semana=dia_semana_de(DIA) if dia_semana is None else dia_semana,
        minutos_inicio=inicio,
        minutos_fim=fim,
    )


def _bloqueio_semanal(inicio, fim, dia_semana=None):
    return SimpleNamespace(
        repete_semanalmente=True,
        dia_semana=dia_semana_de(DIA) if dia_semana is None else dia_semana,
        minutos_inicio=inicio,
        minutos_fim=fim,
        inicio=None,
        fim=None,
    )


def _bloqueio_pontual(inicio, fim):
    return SimpleNamespace(
        repete_semanalmente=False,
        dia_semana=None,
        minutos_inicio=None,
        minutos_fim=None,
        inicio=inicio,
        fim=fim,
    )


def _horas(slots):
    from tenant.datas import formatar_hora

    return [formatar_hora(s.inicio) for s in slots]


def _rodar(duracao=30, expediente=None, bloqueios=(), agendamentos=(), agora=ONTEM):
    return slots_livres(
        barbeiro_id="b1",
        duracao_min=duracao,
        expediente=[_jornada()] if expediente is None else expediente,
        bloqueios=list(bloqueios),
        agendamentos=list(agendamentos),
        dia=DIA,
        agora=agora,
    )


# ------------------------------------------------------------------ a grade


def test_a_grade_anda_de_30_em_30_mesmo_com_servico_de_40():
    """O passo e a GRANULARIDADE, nao a duracao. Um corte de 40 minutos comeca
    as 9:00, 9:30, 10:00 — nao de 40 em 40.
    """
    horas = _horas(_rodar(duracao=40))
    assert horas[:4] == ["09:00", "09:30", "10:00", "10:30"]


def test_o_ultimo_horario_nao_estoura_o_expediente():
    """Com expediente ate as 18h e servico de 40 min, as 17:40 nao pode ser
    oferecido: o corte terminaria as 18:20, depois de fechar. O ultimo que cabe
    e as 17:00.
    """
    assert _horas(_rodar(duracao=40))[-1] == "17:00"


def test_sem_jornada_no_dia_nao_ha_horario():
    """Fechar e APAGAR a linha do dia, nao gravar uma de duracao zero. Entao
    "nao achei jornada" e simplesmente fechado, e nao erro.
    """
    assert _rodar(expediente=[_jornada(dia_semana=0)]) == []
    assert _rodar(expediente=[]) == []


# --------------------------------------------------------- o que ja passou


def test_horario_que_ja_passou_nao_aparece():
    agora = local_para_utc(DIA, 10 * 60 + 1)
    assert _horas(_rodar(agora=agora))[0] == "10:30"


def test_o_horario_EXATO_de_agora_ainda_vale():
    """A antecedencia minima e zero: `inicio < limite` recusa, `==` passa. Um
    `<=` aqui comeria o horario das 10h em ponto para quem abre a tela as 10h
    em ponto, e ninguem ligaria as duas coisas.
    """
    agora = local_para_utc(DIA, 10 * 60)
    assert _horas(_rodar(agora=agora))[0] == "10:00"


# ------------------------------------------------------------- as colisoes


def test_quem_termina_quando_o_outro_comeca_NAO_colide():
    """Intervalos semiabertos. Trocar um `<` por `<=` no `colide` faria a
    agenda perder um horario a cada agendamento — e o sintoma seria "sumiu um
    horario", nunca "a comparacao esta errada".
    """
    a = local_para_utc(DIA, 10 * 60)
    b = a + timedelta(minutes=30)
    c = b + timedelta(minutes=30)
    assert colide(a, b, b, c) is False
    assert colide(a, c, b, c) is True


def test_agendamento_confirmado_tira_o_horario_e_so_ele():
    marcado = SimpleNamespace(
        inicio=local_para_utc(DIA, 10 * 60), fim=local_para_utc(DIA, 10 * 60 + 30)
    )
    horas = _horas(_rodar(agendamentos=[marcado]))
    assert "10:00" not in horas
    assert "09:30" in horas and "10:30" in horas


def test_agendamento_longo_tira_todos_os_horarios_que_ele_cobre():
    marcado = SimpleNamespace(
        inicio=local_para_utc(DIA, 10 * 60), fim=local_para_utc(DIA, 11 * 60 + 30)
    )
    horas = _horas(_rodar(agendamentos=[marcado]))
    for sumiu in ("10:00", "10:30", "11:00"):
        assert sumiu not in horas
    assert "09:30" in horas and "11:30" in horas


def test_agendamento_com_data_sem_fuso_e_tratado_como_UTC():
    """As colunas sao `timestamp WITHOUT time zone`. Sem o `como_utc`, este
    caso ou estoura na comparacao ou — pior — desloca tudo em 3 horas e some
    com o horario errado, sem erro nenhum.
    """
    cru = local_para_utc(DIA, 10 * 60).replace(tzinfo=None)
    marcado = SimpleNamespace(inicio=cru, fim=cru + timedelta(minutes=30))
    assert "10:00" not in _horas(_rodar(agendamentos=[marcado]))


# ------------------------------------------------------------- os bloqueios


def test_bloqueio_semanal_no_dia_certo_tira_o_almoco():
    horas = _horas(_rodar(bloqueios=[_bloqueio_semanal(12 * 60, 13 * 60)]))
    assert "12:00" not in horas and "12:30" not in horas
    assert "11:30" in horas and "13:00" in horas


def test_bloqueio_semanal_de_OUTRO_dia_da_semana_nao_vale():
    outro = (dia_semana_de(DIA) + 1) % 7
    horas = _horas(_rodar(bloqueios=[_bloqueio_semanal(12 * 60, 13 * 60, dia_semana=outro)]))
    assert "12:00" in horas


def test_bloqueio_pontual_de_outra_data_nao_vale():
    de_amanha = local_para_utc("2026-08-13", 12 * 60)
    horas = _horas(
        _rodar(bloqueios=[_bloqueio_pontual(de_amanha, de_amanha + timedelta(hours=1))])
    )
    assert "12:00" in horas


def test_bloqueio_do_dia_inteiro_bloqueia_MESMO():
    """0h as 24h. Do lado TypeScript isto ja falhou calado: 1440 minutos viravam
    a string `T24:00:00`, que e data INVALIDA, e comparacao com data invalida e
    sempre falsa — o bloqueio do dia inteiro nao bloqueava nada.
    """
    assert _rodar(bloqueios=[_bloqueio_semanal(0, 24 * 60)]) == []


def test_a_traducao_dos_bloqueios_serve_para_desenhar_o_dia():
    """`bloqueios_do_dia` e exportada porque o quadro do painel vai precisar
    EXATAMENTE desta traducao. Uma segunda copia seria uma segunda regra de
    recorrencia, e a que diverge e sempre a que ninguem esta olhando.
    """
    faixas = bloqueios_do_dia(
        [_bloqueio_semanal(12 * 60, 13 * 60)], DIA, dia_semana_de(DIA)
    )
    assert faixas == [(local_para_utc(DIA, 12 * 60), local_para_utc(DIA, 13 * 60))]


# ---------------------------------------------------------------- o "qualquer"


def _slot(minutos, barbeiro):
    from app.services.slots import Slot

    inicio = local_para_utc(DIA, minutos)
    return Slot(inicio=inicio, fim=inicio + timedelta(minutes=30), barbeiro_id=barbeiro)


def test_mesmo_instante_em_dois_barbeiros_vira_um_slot_do_de_menor_ordem():
    """O desempate decide quem recebe o cliente que nao escolheu ninguem, e
    tem que ser ESTAVEL: sem criterio, a mesma tela recarregada duas vezes
    ofereceria barbeiros diferentes e o cliente veria o nome mudar debaixo do
    dedo.
    """
    unidos = unir_slots(
        [[_slot(600, "segundo")], [_slot(600, "primeiro")]],
        {"primeiro": 0, "segundo": 1},
    )
    assert [s.barbeiro_id for s in unidos] == ["primeiro"]


def test_a_ordem_do_argumento_nao_decide_nada():
    """O mesmo caso com as listas trocadas de lugar tem que dar o mesmo
    resultado — senao o desempate seria "quem chegou primeiro", disfarcado.
    """
    a = unir_slots([[_slot(600, "x")], [_slot(600, "y")]], {"x": 0, "y": 1})
    b = unir_slots([[_slot(600, "y")], [_slot(600, "x")]], {"x": 0, "y": 1})
    assert a[0].barbeiro_id == b[0].barbeiro_id == "x"


def test_barbeiro_fora_do_mapa_de_ordem_perde_o_desempate_sem_estourar():
    unidos = unir_slots([[_slot(600, "sem")], [_slot(600, "com")]], {"com": 5})
    assert unidos[0].barbeiro_id == "com"


def test_slots_de_instantes_diferentes_saem_todos_e_em_ordem():
    unidos = unir_slots([[_slot(660, "a")], [_slot(600, "b")]], {"a": 0, "b": 1})
    assert _horas(unidos) == ["10:00", "11:00"]
