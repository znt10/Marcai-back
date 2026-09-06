"""O arquivo `.ics` do agendamento, e o link do Google Agenda.

## Por que um arquivo servido pelo servidor, e não montado no navegador

A tela já tinha um "salvar no calendário", e ele era um `Blob` com
`a.download = 'agendamento.ics'`. Isso funciona no Android e no computador, e
**não funciona no iPhone**: o Safari do iOS ignora o atributo `download` em
URL `blob:`. O botão não fazia nada, ou abria o texto cru do arquivo na tela.

Servido de uma URL de verdade, com `Content-Type: text/calendar`, o iOS
reconhece e abre a folha "Adicionar Evento" do Calendário. É o mesmo arquivo;
o que muda é de onde ele vem.

## Por que UTC, e não um bloco VTIMEZONE

O jeito alternativo é escrever a hora local mais um `VTIMEZONE` descrevendo
America/Sao_Paulo — regra de horário de verão inclusive, que o Brasil já teve
e pode ter de novo. É onde esse tipo de arquivo sai uma hora errado, e o erro
só aparece no calendário de quem recebeu.

Em UTC (`DTSTART:20260910T120000Z`) não há o que interpretar: todo cliente de
calendário converte para o fuso do aparelho, e o aparelho do cliente é o que
manda mesmo.
"""

from datetime import datetime, timezone
from urllib.parse import urlencode

# O `PRODID` é obrigatório no RFC 5545. Alguns clientes recusam o arquivo sem
# ele — em silêncio, que é o pior jeito de recusar.
PRODID = "-//Marcai//Agendamento//PT-BR"


def _instante(quando: datetime) -> str:
    """`20260910T120000Z`. Sempre UTC, sempre com o `Z` — ver o cabeçalho."""
    return quando.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escapar(texto: str) -> str:
    """A barra invertida vem PRIMEIRO, senão ela escaparia as barras que as
    substituições seguintes acabaram de pôr — e o nome de serviço com vírgula
    (`Corte, barba e bigode`) sairia partido em três valores."""
    return (
        texto.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _dobrar(linha: str) -> list[str]:
    """Dobra em 75 OCTETOS, como o RFC manda — não em 75 caracteres.

    A diferença aparece em português: "Sobrancelha" tem 11 caracteres e 11
    octetos, mas "Endereço" tem 8 caracteres e 9 octetos. Contando caracteres,
    uma linha de endereço com acentos passa do limite sem ninguém ver, e o
    cliente de calendário que aplica o limite ao pé da letra corta no meio de
    um caractere de dois bytes — o resultado é acento trocado por lixo.

    A continuação começa com UM espaço, que o leitor descarta ao juntar.
    """
    bruto = linha.encode("utf-8")
    if len(bruto) <= 75:
        return [linha]

    partes: list[str] = []
    atual = bytearray()
    limite = 75
    for caractere in linha:
        c = caractere.encode("utf-8")
        if len(atual) + len(c) > limite:
            partes.append(atual.decode("utf-8"))
            atual = bytearray()
            # A partir da segunda, a linha começa com um espaço que conta para
            # o limite — daí 74 e não 75.
            limite = 74
        atual += c
    partes.append(atual.decode("utf-8"))
    return [partes[0]] + [f" {p}" for p in partes[1:]]


def ics_do_agendamento(
    *, codigo: str, servico_nome: str, barbeiro_nome: str, barbearia_nome: str,
    inicio: datetime, fim: datetime, endereco: str, status: str, agora: datetime,
) -> str:
    """O arquivo inteiro, em texto. CRLF entre as linhas, que é o que o RFC
    manda e o que o Outlook exige para não juntar tudo numa linha só."""
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        # `PUBLISH` e não `REQUEST`: `REQUEST` é convite, e convite espera
        # resposta ("aceitar/recusar") de um participante que aqui não existe.
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        # O UID identifica o evento para SEMPRE. Sendo o código do
        # agendamento, baixar duas vezes atualiza o mesmo evento em vez de
        # criar um segundo — e é o que faz o cancelamento abaixo achar o
        # evento certo para marcar como cancelado.
        f"UID:{codigo}@marcai",
        f"DTSTAMP:{_instante(agora)}",
        f"DTSTART:{_instante(inicio)}",
        f"DTEND:{_instante(fim)}",
        f"SUMMARY:{_escapar(f'{servico_nome} com {barbeiro_nome}')}",
        f"LOCATION:{_escapar(endereco)}",
        f"DESCRIPTION:{_escapar(f'{barbearia_nome} — {servico_nome} com {barbeiro_nome}.')}",
    ]

    # Um agendamento cancelado ainda tem página e ainda tem este arquivo. Quem
    # já tinha salvo no calendário e baixa de novo recebe o MESMO UID marcado
    # como cancelado — o calendário risca o evento em vez de criar um segundo.
    if status != "CONFIRMADO":
        linhas.append("STATUS:CANCELLED")

    linhas += ["END:VEVENT", "END:VCALENDAR"]

    dobradas: list[str] = []
    for linha in linhas:
        dobradas.extend(_dobrar(linha))
    # O `\r\n` final não é enfeite: arquivo terminado sem quebra de linha é
    # outro jeito de um cliente recusar em silêncio.
    return "\r\n".join(dobradas) + "\r\n"


def link_do_google_agenda(
    *, servico_nome: str, barbeiro_nome: str, barbearia_nome: str,
    inicio: datetime, fim: datetime, endereco: str,
) -> str:
    """O outro caminho, e ele existe porque o `.ics` não cobre todo mundo.

    O arquivo resolve iPhone e Android — o aparelho abre o calendário nativo.
    Quem usa Google Agenda no navegador (no computador, ou no Android com a
    conta do trabalho) prefere o link que já abre lá com tudo preenchido: não
    baixa nada, não precisa achar o arquivo depois.

    São dois botões porque são dois caminhos diferentes; nenhum dos dois serve
    os dois casos.
    """
    formato = "%Y%m%dT%H%M%SZ"
    parametros = {
        "action": "TEMPLATE",
        "text": f"{servico_nome} com {barbeiro_nome}",
        "dates": (
            f"{inicio.astimezone(timezone.utc).strftime(formato)}/"
            f"{fim.astimezone(timezone.utc).strftime(formato)}"
        ),
        "location": endereco,
        "details": f"{barbearia_nome} — {servico_nome} com {barbeiro_nome}.",
    }
    return f"https://calendar.google.com/calendar/render?{urlencode(parametros)}"
