import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.resumo import cortes_por_barbeiro, periodo_pedido
from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

# 2026-09-05 e' um sabado. AGORA e' o meio da tarde, para que "as 9h" seja
# passado e "as 18h" seja futuro dentro do MESMO dia — e' o que separa
# "corte feito" de "agenda vendida" sem precisar de dois dias diferentes.
AGORA = datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)  # 14h em Sao Paulo
DIA = "2026-09-05"


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO", ordem=0, ativo=True):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel,
        ativo=ativo, ordem=ordem,
    )


def _cliente(barbearia_id, nome="Cliente"):
    from tenant.models import Cliente

    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )


def _servico(barbearia_id, nome="Corte"):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id,
        nome=f"{nome} {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )


def _agendamento(barbearia_id, barbeiro, cliente, servico, inicio,
                 duracao_min=30, status="CONFIRMADO"):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id,
        codigo=uuid.uuid4().hex[:10], barbeiro_id=barbeiro.id,
        cliente_id=cliente.id, servico_id=servico.id, servico_nome=servico.nome,
        inicio=inicio, fim=inicio + timedelta(minutes=duracao_min),
        duracao_min=duracao_min, status=status,
    )


def _linha_de(saida, barbeiro_id):
    """Busca por id, nunca por posicao: a fixture `cenario` ja cria um
    barbeiro padrao por barbearia, entao linhas[0] nem sempre e' o barbeiro
    que o teste configurou."""
    return next(l for l in saida["linhas"] if l["barbeiroId"] == barbeiro_id)


# ---------------------------------------------------------------- contagem


def test_conta_cortes_e_clientes_distintos(cenario):
    """O mesmo cliente voltando duas vezes conta 2 cortes e 1 cliente — e' a
    razao das duas colunas existirem em vez de uma."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    servico = _servico(b.id)
    volta = _cliente(b.id, "Volta Sempre")
    outro = _cliente(b.id, "Passou Uma Vez")

    _agendamento(b.id, zeca, volta, servico, datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
    _agendamento(b.id, zeca, volta, servico, datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc))
    _agendamento(b.id, zeca, outro, servico, datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc))

    saida = cortes_por_barbeiro(b.id, DIA, DIA, AGORA)
    linha = _linha_de(saida, zeca.id)
    assert linha["cortes"] == 3
    assert linha["clientes"] == 2


def test_cancelado_nao_conta(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    servico = _servico(b.id)
    cliente = _cliente(b.id)

    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc),
                 status="CANCELADO_CLIENTE")
    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc),
                 status="CANCELADO_BARBEIRO")

    assert _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), zeca.id)["cortes"] == 1


def test_agendamento_futuro_nao_conta(cenario):
    """Marcado para as 18h de hoje, com AGORA as 14h: e' agenda vendida, nao
    corte feito. Contar isso faria o numero do dia so' cair conforme
    cancelamentos aparecessem."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    servico = _servico(b.id)
    cliente = _cliente(b.id)

    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))  # 9h local, passado
    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc))  # 18h local, futuro

    assert _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), zeca.id)["cortes"] == 1


def test_em_andamento_nao_conta(cenario):
    """Comecou as 13h50 e termina as 14h20, com AGORA as 14h. O criterio e'
    `fim <= agora`: enquanto a tesoura esta na mao, o corte nao entrou."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    _agendamento(b.id, zeca, _cliente(b.id), _servico(b.id),
                 datetime(2026, 9, 5, 16, 50, tzinfo=timezone.utc), duracao_min=30)

    assert _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), zeca.id)["cortes"] == 0


def test_fora_da_janela_nao_conta(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    servico = _servico(b.id)
    cliente = _cliente(b.id)

    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc))  # vespera
    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))  # o dia

    assert _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), zeca.id)["cortes"] == 1
    assert _linha_de(
        cortes_por_barbeiro(b.id, "2026-09-04", DIA, AGORA), zeca.id
    )["cortes"] == 2


# ---------------------------------------------------------------- o eixo


def test_barbeiro_sem_corte_aparece_com_zero(cenario):
    """Quem PAROU e' exatamente o que o dono precisa ver. Se a linha sumisse,
    a tela mostraria so' quem trabalhou e o resumo perderia a metade util."""
    b = cenario["brutus"]
    parado = _barbeiro(b.id, "Parado")

    linha = _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), parado.id)
    assert linha["cortes"] == 0
    assert linha["clientes"] == 0


def test_inativo_com_corte_no_periodo_aparece(cenario):
    """Mesma regra do quadro do dia: desligar o barbeiro nao pode reescrever
    o passado — o resumo de agosto continua tendo que fechar."""
    b = cenario["brutus"]
    saiu = _barbeiro(b.id, "Saiu da equipe", ativo=False)
    _agendamento(b.id, saiu, _cliente(b.id), _servico(b.id),
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))

    linha = _linha_de(cortes_por_barbeiro(b.id, DIA, DIA, AGORA), saiu.id)
    assert linha["cortes"] == 1
    assert linha["ativo"] is False


def test_inativo_sem_corte_no_periodo_nao_aparece(cenario):
    b = cenario["brutus"]
    saiu = _barbeiro(b.id, "Saiu ha' tempos", ativo=False)

    saida = cortes_por_barbeiro(b.id, DIA, DIA, AGORA)
    assert all(l["barbeiroId"] != saiu.id for l in saida["linhas"])


def test_ordem_segue_a_da_equipe(cenario):
    b = cenario["brutus"]
    segundo = _barbeiro(b.id, "Segundo", ordem=2)
    primeiro = _barbeiro(b.id, "Primeiro", ordem=1)

    ids = [l["barbeiroId"] for l in cortes_por_barbeiro(b.id, DIA, DIA, AGORA)["linhas"]]
    assert ids.index(primeiro.id) < ids.index(segundo.id)


# ---------------------------------------------------------------- totais


def test_total_de_clientes_e_distinto_na_barbearia(cenario):
    """O mesmo cliente cortando com dois barbeiros conta 1 em cada linha e 1
    no total — entao a soma das linhas PODE passar do total, e isso e' certo,
    nao bug. A tela rotula em vez de esconder."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    tuca = _barbeiro(b.id, "Tuca")
    servico = _servico(b.id)
    cliente = _cliente(b.id, "O mesmo")

    _agendamento(b.id, zeca, cliente, servico,
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
    _agendamento(b.id, tuca, cliente, servico,
                 datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc))

    saida = cortes_por_barbeiro(b.id, DIA, DIA, AGORA)
    assert saida["totais"]["cortes"] == 2
    assert saida["totais"]["clientes"] == 1
    assert _linha_de(saida, zeca.id)["clientes"] == 1
    assert _linha_de(saida, tuca.id)["clientes"] == 1


# ---------------------------------------------------------------- isolamento


def test_nao_ve_corte_de_outra_barbearia(cenario):
    """O unico teste de isolamento que vale e' o que tem de quem se isolar."""
    b, d = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b.id, "Zeca")
    alheio = _barbeiro(d.id, "Alheio")
    _agendamento(d.id, alheio, _cliente(d.id), _servico(d.id),
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))

    saida = cortes_por_barbeiro(b.id, DIA, DIA, AGORA)
    assert saida["totais"]["cortes"] == 0
    assert all(l["barbeiroId"] != alheio.id for l in saida["linhas"])
    assert _linha_de(saida, zeca.id)["cortes"] == 0


# ------------------------------------------------------- periodo (puro)


def test_periodo_padrao_e_o_mes_corrente():
    assert periodo_pedido(None, None, "2026-09-05") == ("2026-09-01", "2026-09-05")


def test_periodo_aceita_intervalo_valido():
    assert periodo_pedido("2026-08-01", "2026-08-31", "2026-09-05") == (
        "2026-08-01", "2026-08-31",
    )


def test_periodo_recusa_forma_invalida():
    assert periodo_pedido("ontem", "hoje", "2026-09-05") == ("2026-09-01", "2026-09-05")


def test_periodo_recusa_data_impossivel():
    """`\\d{4}-\\d{2}-\\d{2}` casa com 2026-13-45, que nao e' data. Sem o
    `fromisoformat`, isso viraria ValueError la' dentro do servico — 500 numa
    query string malformada."""
    assert periodo_pedido("2026-13-45", "2026-09-05", "2026-09-05") == (
        "2026-09-01", "2026-09-05",
    )


def test_periodo_recusa_invertido():
    assert periodo_pedido("2026-09-05", "2026-09-01", "2026-09-05") == (
        "2026-09-01", "2026-09-05",
    )


def test_periodo_recusa_janela_absurda():
    """Sem teto, um `?de=1900-01-01` nao derruba nada (a agregacao e' uma
    consulta so'), mas devolve um numero que ninguem pediu e esconde o
    engano. O teto torna o engano visivel: volta para o mes."""
    assert periodo_pedido("1900-01-01", "2026-09-05", "2026-09-05") == (
        "2026-09-01", "2026-09-05",
    )


# ---------------------------------------------------------------- a rota
#
# `from app.services.sessao import COOKIE_SESSAO, emitir` vai junto dos
# imports NO TOPO do arquivo, e nao aqui: import no meio do modulo e' erro de
# lint (E402) e esconde de quem le' o cabecalho que este arquivo fala HTTP.


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )
    return host


def test_rota_responde_o_resumo(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _agendamento(b.id, dono, _cliente(b.id), _servico(b.id),
                 datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))

    r = client.get("/api/painel/resumo", {"de": DIA, "ate": DIA}, headers={"host": host})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["de"] == DIA and corpo["ate"] == DIA
    linha = next(l for l in corpo["linhas"] if l["barbeiroId"] == str(dono.id))
    assert linha["cortes"] == 1
    assert linha["clientes"] == 1


def test_rota_recusa_barbeiro_comum(client, cenario):
    """403 e nao 404: quem chega aqui ja' tem sessao valida e ja' sabe que nao
    e' dono — a mensagem nao conta nada novo. O 404 do painel existe para nao
    revelar REGISTRO alheio, e aqui nao ha registro nenhum em jogo."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca")
    host = _logar(client, zeca, b.id)

    r = client.get("/api/painel/resumo", headers={"host": host})
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono vê o resumo."


def test_rota_recusa_sem_sessao(client, cenario):
    r = client.get("/api/painel/resumo", headers={"host": "brutus.localhost"})
    assert r.status_code == 401


def test_rota_sem_periodo_devolve_o_mes_corrente(client, cenario):
    """A tela abre sem parametro nenhum; o padrao tem que ser util, e util
    aqui e' o mes que esta' correndo."""
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.get("/api/painel/resumo", headers={"host": host})
    assert r.status_code == 200
    corpo = r.json()
    # Sem recalcular "que mes e' hoje" aqui: o teste conferiria a rota contra
    # a MESMA conta que a rota faz, e os dois errariam juntos. O que da' para
    # afirmar de fora e' a FORMA do padrao — comeca no dia 1, e as duas pontas
    # caem no mesmo mes.
    assert corpo["de"].endswith("-01")
    assert corpo["de"][:7] == corpo["ate"][:7]
    assert corpo["ate"] >= corpo["de"]


def test_rota_com_periodo_torto_nao_estoura(client, cenario):
    """A query string vem de link, nao de formulario: `?de=2026-13-45` tem que
    virar o padrao, nunca 500."""
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.get("/api/painel/resumo", {"de": "2026-13-45", "ate": "amanha"},
                   headers={"host": host})
    assert r.status_code == 200
    assert r.json()["de"].endswith("-01")
