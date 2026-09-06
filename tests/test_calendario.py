from datetime import datetime, timedelta, timezone

from app.services.calendario import (
    _dobrar,
    ics_do_agendamento,
    link_do_google_agenda,
)

INICIO = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)  # 9h em Sao Paulo
AGORA = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def _ics(**troca):
    base = dict(
        codigo="abc123", servico_nome="Corte", barbeiro_nome="Nando",
        barbearia_nome="ZNT", inicio=INICIO, fim=INICIO + timedelta(minutes=30),
        endereco="Rua Aurora, 88", status="CONFIRMADO", agora=AGORA,
    )
    return ics_do_agendamento(**{**base, **troca})


def test_o_arquivo_tem_o_que_todo_cliente_de_calendario_exige():
    """`VERSION`, `PRODID`, `UID` e `DTSTAMP` sao obrigatorios no RFC 5545, e
    parte dos clientes recusa o arquivo sem eles — em silencio, que e' o pior
    jeito de recusar."""
    texto = _ics()
    for exigido in ("BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:", "BEGIN:VEVENT",
                    "UID:abc123@marcai", "DTSTAMP:", "END:VEVENT", "END:VCALENDAR"):
        assert exigido in texto, exigido


def test_as_linhas_terminam_em_CRLF_e_o_arquivo_tambem():
    """O Outlook junta tudo numa linha so' com `\\n` puro, e arquivo terminado
    sem quebra e' outro jeito de ser recusado calado."""
    texto = _ics()
    assert "\r\n" in texto
    assert texto.endswith("\r\n")
    # Nenhum \n solto: todo \n do arquivo tem um \r na frente.
    assert texto.replace("\r\n", "") .count("\n") == 0


def test_a_hora_sai_em_UTC_com_Z():
    """O alternativo seria a hora local mais um bloco VTIMEZONE descrevendo
    America/Sao_Paulo, horario de verao inclusive — que o Brasil ja teve e
    pode ter de novo. E' onde esse arquivo sai uma hora errado, e o erro so'
    aparece no calendario de quem recebeu."""
    texto = _ics()
    assert "DTSTART:20260910T120000Z" in texto
    assert "DTEND:20260910T123000Z" in texto


def test_virgula_no_nome_do_servico_nao_parte_o_valor():
    """Sem escape, "Corte, barba e bigode" viraria tres valores para o parser
    e o evento chegaria com o nome cortado."""
    texto = _ics(servico_nome="Corte, barba e bigode")
    assert "SUMMARY:Corte\\, barba e bigode com Nando" in texto


def test_a_barra_invertida_e_escapada_ANTES_das_outras():
    """Se a barra fosse por ultimo, ela escaparia as barras que o escape de
    virgula e ponto-e-virgula acabaram de por — e o valor sairia com barra
    dobrada onde nao devia."""
    texto = _ics(endereco="Rua A\\B, 10")
    assert "LOCATION:Rua A\\\\B\\, 10" in texto


def test_agendamento_cancelado_vira_evento_cancelado():
    """Mesmo UID: quem ja tinha salvo e baixa de novo tem o evento RISCADO no
    calendario, em vez de ganhar um segundo evento fantasma."""
    assert "STATUS:CANCELLED" in _ics(status="CANCELADO_CLIENTE")
    assert "STATUS:CANCELLED" not in _ics()


def test_linha_longa_e_dobrada_em_75_OCTETOS_nao_caracteres():
    """A diferenca aparece em portugues: "Endereço" tem 8 caracteres e 9
    octetos. Contando caracteres, uma linha com acentos passa do limite sem
    ninguem ver, e o cliente que aplica o limite ao pe da letra corta no meio
    de um caractere de dois bytes — acento vira lixo."""
    linha = "LOCATION:" + "çã" * 60
    partes = _dobrar(linha)
    assert len(partes) > 1
    for p in partes:
        assert len(p.encode("utf-8")) <= 75, p
    # A continuacao comeca com UM espaco, que o leitor descarta ao juntar.
    for p in partes[1:]:
        assert p.startswith(" ")
    # Nada se perdeu nem se duplicou.
    assert "".join([partes[0]] + [p[1:] for p in partes[1:]]) == linha


def test_linha_curta_nao_e_dobrada():
    assert _dobrar("SUMMARY:Corte") == ["SUMMARY:Corte"]


def test_o_link_do_google_leva_titulo_data_e_lugar():
    """O outro caminho: o `.ics` resolve iPhone e Android, e quem usa Google
    Agenda no navegador prefere o link que ja abre la preenchido."""
    link = link_do_google_agenda(
        servico_nome="Corte", barbeiro_nome="Nando", barbearia_nome="ZNT",
        inicio=INICIO, fim=INICIO + timedelta(minutes=30), endereco="Rua Aurora, 88",
    )
    assert link.startswith("https://calendar.google.com/calendar/render?")
    assert "action=TEMPLATE" in link
    assert "dates=20260910T120000Z%2F20260910T123000Z" in link
    # O que vai na query tem de estar percent-encoded, senao o espaco e a
    # virgula quebram a URL.
    assert "Rua+Aurora%2C+88" in link
