"""As conversoes de fuso e de calendario. Sem banco.

Este arquivo existe por causa de uma linha so — `dia_semana_de` — mas cobre o
modulo inteiro porque tudo aqui e do tipo que erra em silencio: hora deslocada,
dia da semana trocado e rotulo com o dia errado nao levantam excecao nenhuma.
"""

from datetime import datetime, timezone

from tenant.datas import (
    como_utc,
    dia_de_hoje,
    dia_semana_de,
    formatar_dia_longo,
    formatar_hora,
    local_para_utc,
    somar_dias,
    utc_para_local,
)


def test_domingo_e_ZERO():
    """A linha mais facil de errar do projeto. O banco guarda o que o
    `getDay()` do JavaScript produz (domingo = 0); o `weekday()` do Python
    conta de segunda. Usar o do Python cru desloca a semana inteira: o
    expediente de terca passaria a valer na segunda, e a agenda ficaria
    coerente consigo mesma o bastante para ninguem desconfiar.
    """
    # 09/08/2026 e um domingo.
    assert dia_semana_de("2026-08-09") == 0
    assert dia_semana_de("2026-08-10") == 1  # segunda
    assert dia_semana_de("2026-08-12") == 3  # quarta
    assert dia_semana_de("2026-08-15") == 6  # sabado


def test_a_hora_local_vira_o_instante_utc_certo():
    """Sao Paulo e UTC-3 e nao tem mais horario de verao. 9h daqui e 12h UTC —
    se isto sair errado, TODA a grade sai deslocada em 3 horas.
    """
    assert local_para_utc("2026-08-12", 9 * 60) == datetime(
        2026, 8, 12, 12, 0, tzinfo=timezone.utc
    )


def test_1440_minutos_transborda_para_o_dia_seguinte():
    """"O dia inteiro" num intervalo semiaberto e 0..1440. Sem o transbordo
    isto seria hora 24, que nao existe — e do lado TypeScript virava data
    invalida, com o bloqueio do dia inteiro nao bloqueando nada em silencio.
    """
    assert local_para_utc("2026-08-12", 24 * 60) == local_para_utc("2026-08-13", 0)


def test_ida_e_volta_entre_local_e_utc():
    for minutos in (0, 9 * 60, 12 * 60 + 30, 23 * 60 + 59):
        assert utc_para_local(local_para_utc("2026-08-12", minutos)) == (
            "2026-08-12",
            minutos,
        )


def test_a_virada_do_dia_e_no_fuso_da_barbearia_e_nao_em_utc():
    """As 22h de Sao Paulo ja e o dia seguinte em UTC. Um `dia_de_hoje` que
    olhasse o UTC cru viraria a agenda a meia-noite ERRADA — as 21h locais.
    """
    vinte_e_duas = datetime(2026, 8, 13, 1, 0, tzinfo=timezone.utc)  # 22h do dia 12
    assert dia_de_hoje(vinte_e_duas) == "2026-08-12"


def test_o_rotulo_longo_e_igualzinho_ao_do_date_fns():
    """Texto conferido no fio contra o `EEEEEE d MMM` + ptBR do outro lado.
    Inclui "sab" SEM acento, que e o que o date-fns devolve — e o tipo de
    detalhe que so aparece comparando as duas respostas byte a byte.
    """
    esperado = {
        "2026-01-04": "dom 4 jan",
        "2026-04-01": "qua 1 abr",
        "2026-08-01": "sab 1 ago",
        "2026-12-25": "sex 25 dez",
    }
    for dia, texto in esperado.items():
        assert formatar_dia_longo(local_para_utc(dia, 12 * 60)) == texto


def test_somar_dias_atravessa_mes_e_ano():
    assert somar_dias("2026-08-31", 1) == "2026-09-01"
    assert somar_dias("2026-12-31", 1) == "2027-01-01"
    assert somar_dias("2028-02-28", 1) == "2028-02-29"  # bissexto
    assert somar_dias("2026-01-01", -1) == "2025-12-31"


def test_data_sem_fuso_e_lida_como_utc_e_nao_como_hora_da_maquina():
    cru = datetime(2026, 8, 12, 12, 0)
    assert como_utc(cru) == datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    assert formatar_hora(cru) == "09:00"
    # E o que ja tem fuso passa intacto.
    com = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    assert como_utc(com) is com
    assert como_utc(None) is None
