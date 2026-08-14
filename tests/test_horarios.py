import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _dia_de_prova() -> str:
    """Um dia SEMPRE no futuro, e nao uma data escrita a mao.

    A grade descarta horario que ja passou, entao uma data fixa faz a suite
    inteira passar a falhar no dia seguinte — todos os slots somem e o sintoma
    (`slots == []`) nao aponta para o calendario, aponta para o motor. Trinta
    dias a frente cabem na janela de 60 e nao esbarram no teto.
    """
    from django.utils import timezone

    from tenant.datas import dia_de_hoje, somar_dias

    return somar_dias(dia_de_hoje(timezone.now()), 30)


DIA = _dia_de_prova()


def _servico(barbearia_id, nome="Corte"):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome=nome,
        duracao_minima_min=20,
        duracao_sugerida_min=30,
        ativo=True,
    )


def _barbeiro(barbearia_id, nome, ordem=0, ativo=True):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
        ativo=ativo,
        ordem=ordem,
    )


def _vinculo(barbearia_id, barbeiro, servico, duracao=30):
    from tenant.models import BarbeiroServico

    return BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id,
        servico_id=servico.id,
        barbearia_id=barbearia_id,
        duracao_min=duracao,
        ativo=True,
    )


def _expediente(barbearia_id, barbeiro, dia=DIA, inicio=9 * 60, fim=18 * 60):
    from tenant.datas import dia_semana_de
    from tenant.models import HorarioTrabalho

    return HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        barbeiro_id=barbeiro.id,
        dia_semana=dia_semana_de(dia),
        minutos_inicio=inicio,
        minutos_fim=fim,
    )


def _marcar(barbearia_id, barbeiro, servico, minutos, duracao=30, status="CONFIRMADO"):
    from tenant.datas import local_para_utc
    from tenant.models import Agendamento, Cliente

    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome="Fulano",
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    inicio = local_para_utc(DIA, minutos)
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        codigo=str(uuid.uuid4())[:8],
        barbeiro_id=barbeiro.id,
        cliente_id=cliente.id,
        servico_id=servico.id,
        servico_nome=servico.nome,
        inicio=inicio,
        fim=inicio + timedelta(minutes=duracao),
        duracao_min=duracao,
        status=status,
    )


@pytest.fixture
def pronto(cenario):
    """Uma barbearia com um barbeiro que trabalha das 9h as 18h na quarta e faz
    um corte de 30 minutos.
    """
    b = cenario["brutus"].id
    servico = _servico(b)
    barbeiro = _barbeiro(b, "Zeca")
    _vinculo(b, barbeiro, servico)
    _expediente(b, barbeiro)
    return {"barbearia": b, "servico": servico, "barbeiro": barbeiro}


def _pedir(client, host="brutus.localhost", **busca):
    return client.get("/api/horarios", busca, headers={"host": host})


def _horas(corpo, i=0):
    return [s["hora"] for s in corpo["dias"][i]["slots"]]


# --------------------------------------------------------------- o contrato


def test_o_envelope_e_os_campos_sao_os_mesmos_do_next(client, pronto):
    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json()

    assert set(corpo) == {"dias"}
    assert set(corpo["dias"][0]) == {"data", "rotulo", "slots"}
    assert set(corpo["dias"][0]["slots"][0]) == {
        "hora", "inicio", "fim", "barbeiroId", "barbeiroNome", "duracaoMin",
    }


def test_o_instante_sai_no_formato_do_toISOString(client, pronto):
    """`2026-08-12T12:00:00.000Z` — com os TRES digitos de milissegundo. O
    padrao do DRF nao os imprime e o `%f` imprime seis; sem o campo proprio a
    comparacao byte a byte entre os dois lados falharia por formatacao e
    esconderia qualquer divergencia de verdade.
    """
    from tenant.datas import local_para_utc

    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json()
    primeiro = corpo["dias"][0]["slots"][0]

    # 9h em Sao Paulo e 12h UTC. O esperado e montado, e nao escrito, para o
    # teste nao virar refem da data — mas o FORMATO abaixo e literal, que e o
    # que este caso existe para prender.
    nove = local_para_utc(DIA, 9 * 60)
    assert primeiro["inicio"] == f"{nove.strftime('%Y-%m-%dT%H:%M:%S')}.000Z"
    assert primeiro["inicio"].endswith("T12:00:00.000Z")
    assert primeiro["fim"].endswith("T12:30:00.000Z")


def test_o_rotulo_diz_hoje_e_amanha(client, pronto):
    from django.utils import timezone

    from tenant.datas import dia_de_hoje, somar_dias

    hoje = dia_de_hoje(timezone.now())
    corpo = _pedir(client, servicoId=pronto["servico"].id, dias=2).json()

    assert corpo["dias"][0]["data"] == hoje
    assert corpo["dias"][0]["rotulo"].startswith("hoje · ")
    assert corpo["dias"][1]["data"] == somar_dias(hoje, 1)
    assert corpo["dias"][1]["rotulo"].startswith("amanhã · ")


def test_sem_o_de_a_janela_comeca_hoje_com_o_padrao_de_dois_dias(client, pronto):
    corpo = _pedir(client, servicoId=pronto["servico"].id).json()
    assert len(corpo["dias"]) == 2


# ------------------------------------------------------------- a validacao


def test_sem_servico_da_400_com_a_mensagem_da_tela(client, pronto):
    r = _pedir(client)
    assert r.status_code == 400
    assert r.json() == {"erro": "Escolhe o serviço primeiro."}


def test_data_torta_da_400_em_vez_de_500(client, pronto):
    """O route.ts nao valida `de` e deixa uma data invalida se propagar como
    texto. Aqui isso seria ValueError -> 500. 400 e a unica das tres respostas
    que diz o que aconteceu.
    """
    r = _pedir(client, servicoId=pronto["servico"].id, de="ontem")
    assert r.status_code == 400


def test_dias_ilegivel_cai_no_padrao_em_vez_de_devolver_agenda_vazia(client, pronto):
    """DIVERGE do route.ts de proposito. La `Number('abc')` da NaN e o laco nao
    roda: `?dias=abc` responde 200 com a agenda VAZIA — indistinguivel de uma
    barbearia sem nenhum horario, e o cliente vai embora achando que nao ha
    vaga. Mostrar dois dias e visivelmente diferente de mostrar nada.
    """
    corpo = _pedir(client, servicoId=pronto["servico"].id, dias="abc").json()
    assert len(corpo["dias"]) == 2


def test_a_janela_tem_teto(client, pronto):
    """Sem o teto, um `?dias=100000` viraria cem mil voltas de laco com tres
    consultas cada, dentro de uma transacao aberta.
    """
    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=9999).json()
    assert len(corpo["dias"]) == 60


def test_do_host_do_admin_da_404(client, pronto):
    assert _pedir(client, "admin.localhost", servicoId=pronto["servico"].id).status_code == 404


# ------------------------------------------------------------------ a grade


def test_a_grade_do_dia_sai_inteira(client, pronto):
    horas = _horas(_pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json())
    assert horas[0] == "09:00"
    assert horas[-1] == "17:30"
    assert len(horas) == 18


def test_agendamento_confirmado_tira_o_horario(client, pronto):
    _marcar(pronto["barbearia"], pronto["barbeiro"], pronto["servico"], 10 * 60)
    horas = _horas(_pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json())
    assert "10:00" not in horas and "10:30" in horas


def test_agendamento_CANCELADO_nao_ocupa(client, pronto):
    """O horario tem que voltar para a grade. Um cancelado que continuasse
    ocupando deixaria a vaga morta ate o fim do dia — a barbearia perde
    dinheiro e nada aparece na tela.
    """
    _marcar(
        pronto["barbearia"], pronto["barbeiro"], pronto["servico"], 10 * 60,
        status="CANCELADO_CLIENTE",
    )
    horas = _horas(_pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json())
    assert "10:00" in horas


def test_bloqueio_semanal_tira_o_almoco(client, pronto):
    from tenant.datas import dia_semana_de
    from tenant.models import Bloqueio

    Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=pronto["barbearia"],
        barbeiro_id=pronto["barbeiro"].id,
        motivo="ALMOCO",
        repete_semanalmente=True,
        dia_semana=dia_semana_de(DIA),
        minutos_inicio=12 * 60,
        minutos_fim=13 * 60,
    )
    horas = _horas(_pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json())
    assert "12:00" not in horas and "12:30" not in horas
    assert "11:30" in horas and "13:00" in horas


def test_barbeiro_sem_expediente_no_dia_nao_oferece_nada(client, pronto):
    """O dia seguinte: o barbeiro so declarou o dia da semana do DIA."""
    from tenant.datas import somar_dias

    corpo = _pedir(
        client, servicoId=pronto["servico"].id, de=somar_dias(DIA, 1), dias=1
    ).json()
    assert corpo["dias"][0]["slots"] == []


def test_servico_sem_vinculo_devolve_dia_vazio_e_nao_erro(client, pronto):
    outro = _servico(pronto["barbearia"], nome="Barba")
    corpo = _pedir(client, servicoId=outro.id, de=DIA, dias=1).json()
    assert corpo["dias"][0]["slots"] == []


# ------------------------------------------------------------- o "qualquer"


def test_com_qualquer_o_horario_repetido_fica_com_o_de_menor_ordem(client, pronto):
    b = pronto["barbearia"]
    segundo = _barbeiro(b, "Rael", ordem=5)
    _vinculo(b, segundo, pronto["servico"])
    _expediente(b, segundo)

    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json()
    nomes = {s["barbeiroNome"] for s in corpo["dias"][0]["slots"]}
    assert nomes == {"Zeca"}


def test_o_segundo_barbeiro_aparece_no_horario_em_que_o_primeiro_esta_ocupado(
    client, pronto
):
    """A razao de "tanto faz" existir: com o Zeca ocupado as 10h, a vaga nao
    some — ela passa para o Rael.
    """
    b = pronto["barbearia"]
    segundo = _barbeiro(b, "Rael", ordem=5)
    _vinculo(b, segundo, pronto["servico"])
    _expediente(b, segundo)
    _marcar(b, pronto["barbeiro"], pronto["servico"], 10 * 60)

    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json()
    das_dez = [s for s in corpo["dias"][0]["slots"] if s["hora"] == "10:00"]
    assert [s["barbeiroNome"] for s in das_dez] == ["Rael"]


def test_com_barbeiro_escolhido_so_ele_conta(client, pronto):
    b = pronto["barbearia"]
    segundo = _barbeiro(b, "Rael", ordem=5)
    _vinculo(b, segundo, pronto["servico"])
    _expediente(b, segundo)

    corpo = _pedir(
        client, servicoId=pronto["servico"].id, barbeiroId=segundo.id, de=DIA, dias=1
    ).json()
    assert {s["barbeiroNome"] for s in corpo["dias"][0]["slots"]} == {"Rael"}


def test_barbeiro_desativado_some_da_grade(client, pronto):
    from tenant.models import Barbeiro

    Barbeiro.objects.using("owner").filter(id=pronto["barbeiro"].id).update(ativo=False)
    corpo = _pedir(client, servicoId=pronto["servico"].id, de=DIA, dias=1).json()
    assert corpo["dias"][0]["slots"] == []


def test_o_rls_isola_a_grade_de_uma_barbearia_da_outra(client, pronto):
    """O servico existe — so nao naquele host. Sem o RLS, o id de um servico da
    concorrente devolveria a agenda dela.
    """
    corpo = _pedir(
        client, "dontony.localhost", servicoId=pronto["servico"].id, de=DIA, dias=1
    ).json()
    assert corpo["dias"][0]["slots"] == []


# ---------------------------------------------------------- dias-com-vaga


def _calendario(client, host="brutus.localhost", **busca):
    return client.get("/api/dias-com-vaga", busca, headers={"host": host})


def test_o_calendario_marca_so_os_dias_do_expediente(client, pronto):
    """O barbeiro declarou UM dia da semana. Todo dia devolvido tem que cair
    nesse dia da semana, e o DIA de prova tem que estar entre eles.

    A conferencia e por dia da semana, e nao por uma lista de numeros escrita
    a mao, porque o mes varia com a data em que a suite roda — e os dias ja
    passados nao entram, o que e o comportamento certo.
    """
    from tenant.datas import dia_semana_de

    mes = DIA[:7]
    r = _calendario(client, servicoId=pronto["servico"].id, mes=mes)
    assert r.status_code == 200

    dias = r.json()["dias"]
    assert int(DIA[8:10]) in dias
    assert dias == sorted(dias)
    for d in dias:
        assert dia_semana_de(f"{mes}-{d:02d}") == dia_semana_de(DIA)


def test_o_calendario_recusa_mes_sem_forma_de_mes(client, pronto):
    for mes in (None, "agosto", "2026-8", "2026-08-12"):
        busca = {"servicoId": pronto["servico"].id}
        if mes is not None:
            busca["mes"] = mes
        r = _calendario(client, **busca)
        assert r.status_code == 400, f"mes={mes!r} deveria dar 400"
        assert r.json() == {"erro": "Parâmetros inválidos."}


def test_o_calendario_recusa_mes_13(client, pronto):
    """O regex garante a FORMA, nao o valor: `2026-13` passa por ele e
    estouraria no calendario.
    """
    r = _calendario(client, servicoId=pronto["servico"].id, mes="2026-13")
    assert r.status_code == 400


def test_o_calendario_sem_servico_da_400(client, pronto):
    assert _calendario(client, mes="2026-08").status_code == 400


def test_o_calendario_de_fevereiro_bissexto_vai_ate_29(client, pronto):
    """Sem `monthrange`, o ultimo dia sairia de aritmetica de data e fevereiro
    e onde isso erra.

    O expediente vai num barbeiro NOVO, e nao no do cenario: `HorarioTrabalho`
    tem `@@unique([barbeiroId, diaSemana])`, e o dia da semana do DIA de prova
    muda conforme a data em que a suite roda — uma vez a cada sete dias ele
    coincidiria com o de 29/02/2028 e o teste quebraria por violacao de unique,
    sem nada a ver com o que ele mede.
    """
    b = pronto["barbearia"]
    outro = _barbeiro(b, "Do bissexto")
    _vinculo(b, outro, pronto["servico"])
    _expediente(b, outro, dia="2028-02-29")

    r = _calendario(client, servicoId=pronto["servico"].id, mes="2028-02")
    assert 29 in r.json()["dias"]
