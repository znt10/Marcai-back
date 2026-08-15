from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

# UNICO arquivo deste lado que toca fuso, igual ao front/src/lib/datas.ts ser o
# unico que importa date-fns-tz. Espalhar conversao de fuso e o jeito mais
# rapido de produzir bug de agenda que so aparece meses depois.

MINUTOS_DIA = 24 * 60

# Os nomes vem escritos, e nao de `locale`, de proposito. O contrato e o texto
# EXATO que o date-fns produz com `EEEEEE d MMM` + ptBR + `.toLowerCase()`,
# conferido no fio contra o outro lado — inclusive "sab" SEM acento, que e o
# que o date-fns devolve (nao "sáb", como se esperaria). Depender do locale do
# sistema poria o rotulo da tela a merce de qual imagem base o contêiner usa.
_DIAS = ("dom", "seg", "ter", "qua", "qui", "sex", "sab")
_MESES = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


def como_utc(quando: datetime | None) -> datetime | None:
    """Rotula como UTC uma data que veio do banco sem fuso.

    As colunas de data deste banco sao `timestamp WITHOUT time zone`. Nao e
    descuido do Prisma: e o default dele para `DateTime`, e o Prisma grava
    sempre em UTC — o dado esta certo, falta so o rotulo. O Django roda com
    USE_TZ=True e devolve o valor cru do psycopg, sem fuso; comparar isso com
    um `datetime.now(timezone.utc)` estoura com "can't compare offset-naive
    and offset-aware datetimes".

    Rotular como UTC e a conversao CORRETA e nao uma suposicao: e o fuso em que
    o Prisma gravou e o fuso em que o Django manda os parametros (com USE_TZ a
    conexao e fixada em UTC). Se um dia as colunas virarem `timestamptz` no
    schema.prisma, esta funcao vira no-op sozinha.

    Vale para TODA leitura de data destes models — a trava do login foi so
    onde ela apareceu primeiro.
    """
    if quando is None:
        return None
    if quando.tzinfo is None:
        return quando.replace(tzinfo=timezone.utc)
    return quando


def local_para_utc(dia: str, minutos: int) -> datetime:
    """`minutos` PODE ser 1440, e essa e a razao de esta funcao existir em vez
    de uma linha de conversao no lugar do uso.

    1440 e como "o dia inteiro" se escreve num intervalo semiaberto, e tanto a
    jornada quanto o bloqueio usam isso. Sem o transbordo para o dia seguinte,
    a montagem daria hora 24, que nao existe — do lado TypeScript virava
    `T24:00:00`, uma data INVALIDA, e comparacao com data invalida e sempre
    falsa: o bloqueio das 0h as 24h nao bloqueava nada, em silencio. Em Python
    seria um ValueError alto, o que e melhor, mas o resultado certo continua
    sendo o mesmo instante do dia seguinte.

    Nao ha tratamento de horario de verao aqui e nao deve haver: o Brasil o
    aboliu em 2019, entao nao existe hora ambigua nem inexistente em
    America/Sao_Paulo para data futura. Se um dia voltar, este e o lugar — e
    a decisao (qual das duas leituras vale) tem que ser a mesma que o
    `fromZonedTime` do outro lado toma, ou os dois passam a divergir uma vez
    por ano, por uma hora.
    """
    dias_inteiros, do_dia = divmod(minutos, MINUTOS_DIA)
    base = somar_dias(dia, dias_inteiros) if dias_inteiros else dia

    ano, mes, d = (int(p) for p in base.split("-"))
    local = datetime(ano, mes, d, do_dia // 60, do_dia % 60, tzinfo=FUSO)
    return local.astimezone(timezone.utc)


def utc_para_local(quando: datetime) -> tuple[str, int]:
    local = _no_fuso(quando)
    return local.strftime("%Y-%m-%d"), local.hour * 60 + local.minute


def formatar_hora(quando: datetime) -> str:
    return _no_fuso(quando).strftime("%H:%M")


def formatar_dia_curto(quando: datetime) -> str:
    """"13/08" — porte de `formatarDiaCurto`. Usado so na recusa de
    desativar barbeiro com agenda futura: pelo fuso da BARBEARIA, nao do
    servidor, senao um horario das 22h daqui apontaria o dia seguinte."""
    return _no_fuso(quando).strftime("%d/%m")


def formatar_dia_longo(quando: datetime) -> str:
    """"qua 13 ago" — o dia SEM zero a esquerda, que e o que o `d` do date-fns
    faz e o que `%d` do strftime nao faz.
    """
    local = _no_fuso(quando)
    return f"{_DIAS[dia_semana_de(local.strftime('%Y-%m-%d'))]} {local.day} {_MESES[local.month - 1]}"


def dia_de_hoje(agora: datetime) -> str:
    return utc_para_local(agora)[0]


def somar_dias(dia: str, n: int) -> str:
    """Aritmetica de DATA, nao de instante — e por isso nao precisa da ancora
    ao meio-dia que o lado TypeScript usa. La `somarDias` soma num `Date`, que
    e um instante, e a partir da meia-noite qualquer deslocamento de fuso
    empurraria o resultado para o dia anterior. `datetime.date` nao tem fuso e
    nao tem esse buraco.
    """
    return (date.fromisoformat(dia) + timedelta(days=n)).isoformat()


def dia_semana_de(dia: str) -> int:
    """0 = DOMINGO, e essa e a linha mais facil de errar deste arquivo.

    O banco guarda o que o `getDay()` do JavaScript produz — domingo = 0. O
    `weekday()` do Python conta de segunda (segunda = 0) e o `isoweekday()`
    conta de segunda comecando em 1. Usar qualquer um dos dois cru desloca a
    semana inteira em um dia: o expediente de terca passaria a valer na
    segunda, e a agenda ficaria coerente consigo mesma o suficiente para
    ninguem desconfiar do calculo.
    """
    return date.fromisoformat(dia).isoweekday() % 7


def _no_fuso(quando: datetime) -> datetime:
    """Rotula ANTES de converter. Sem o `como_utc`, o `astimezone` leria o
    valor como hora LOCAL DA MAQUINA e o horario sairia deslocado em 3 horas,
    sem erro nenhum — o pior jeito de errar hora numa agenda.
    """
    return como_utc(quando).astimezone(FUSO)
