import uuid

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _servico(barbearia_id, nome="Corte", ativo=True, ordem=0):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome=nome,
        duracao_minima_min=20,
        duracao_sugerida_min=30,
        ativo=ativo,
        ordem=ordem,
    )


def _barbeiro(barbearia_id, nome, ativo=True):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
        ativo=ativo,
    )


def _vinculo(barbearia_id, barbeiro, servico, duracao=30, ativo=True):
    from tenant.models import BarbeiroServico

    return BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id,
        servico_id=servico.id,
        barbearia_id=barbearia_id,
        duracao_min=duracao,
        ativo=ativo,
    )


def _pedir(client, host="brutus.localhost", **busca):
    return client.get("/api/servicos", busca, headers={"host": host})


def test_o_envelope_e_os_campos_sao_os_mesmos_do_next(client, cenario):
    b = cenario["brutus"]
    _vinculo(b.id, _barbeiro(b.id, "Zeca"), _servico(b.id))

    corpo = _pedir(client).json()
    assert set(corpo) == {"servicos"}
    assert set(corpo["servicos"][0]) == {"id", "nome", "duracaoMin"}
    # `ordem` e chave de ordenacao e nao pode vazar: se vazasse, a tela
    # ganharia a tentacao de reordenar por conta propria e passariam a existir
    # duas ordenacoes, uma em cada lado.
    assert "ordem" not in corpo["servicos"][0]


def test_servico_sem_vinculo_nenhum_nao_aparece(client, cenario):
    """Escolher um servico que ninguem faz leva a uma tela de horarios vazia,
    sem erro. E o mesmo beco sem saida que a lista de barbeiros evita.
    """
    _servico(cenario["brutus"].id)
    assert _pedir(client).json()["servicos"] == []


def test_as_tres_condicoes_valem_JUNTAS(client, cenario):
    """Vinculo ativo, barbeiro ativo e servico ativo. Cada caso abaixo desliga
    UMA das tres e o servico tem que sumir — um teste que desligasse as tres
    de uma vez passaria mesmo se a rota conferisse so uma.
    """
    b = cenario["brutus"].id

    vinculo_desligado = _servico(b, nome="A")
    _vinculo(b, _barbeiro(b, "Um"), vinculo_desligado, ativo=False)

    barbeiro_desligado = _servico(b, nome="B")
    _vinculo(b, _barbeiro(b, "Dois", ativo=False), barbeiro_desligado)

    servico_desligado = _servico(b, nome="C", ativo=False)
    _vinculo(b, _barbeiro(b, "Tres"), servico_desligado)

    assert _pedir(client).json()["servicos"] == []


def test_com_qualquer_a_duracao_e_a_MENOR_entre_os_barbeiros(client, cenario):
    """Decisao de produto, nao detalhe: o barbeiro so e resolvido na escolha do
    horario. Prometer a duracao MAIOR faria a tela seguinte oferecer menos
    vagas do que existem de verdade.
    """
    b = cenario["brutus"].id
    servico = _servico(b)
    _vinculo(b, _barbeiro(b, "Rapido"), servico, duracao=20)
    _vinculo(b, _barbeiro(b, "Caprichoso"), servico, duracao=45)

    assert _pedir(client).json()["servicos"] == [
        {"id": servico.id, "nome": "Corte", "duracaoMin": 20}
    ]


def test_com_barbeiro_escolhido_a_duracao_e_a_DELE(client, cenario):
    """A metade que o teste acima nao cobre: com o barbeiro definido, a menor
    duracao da barbearia deixa de valer — vale a do vinculo dele. Uma
    implementacao que aplicasse o Min sempre passaria no teste anterior e
    falharia aqui.
    """
    b = cenario["brutus"].id
    servico = _servico(b)
    _vinculo(b, _barbeiro(b, "Rapido"), servico, duracao=20)
    caprichoso = _barbeiro(b, "Caprichoso")
    _vinculo(b, caprichoso, servico, duracao=45)

    corpo = _pedir(client, barbeiroId=caprichoso.id).json()
    assert corpo["servicos"] == [{"id": servico.id, "nome": "Corte", "duracaoMin": 45}]


def test_o_servico_aparece_UMA_vez_mesmo_com_varios_barbeiros(client, cenario):
    """A lista sai dos vinculos, entao sem o agrupamento o mesmo servico
    apareceria uma vez por barbeiro que o faz.
    """
    b = cenario["brutus"].id
    servico = _servico(b)
    for nome in ("Um", "Dois", "Tres"):
        _vinculo(b, _barbeiro(b, nome), servico)

    assert len(_pedir(client).json()["servicos"]) == 1


def test_barbeiro_inexistente_devolve_lista_vazia_e_nao_erro(client, cenario):
    """404 aqui diria a quem chuta ids quais barbeiros existem naquela
    barbearia. Lista vazia e a resposta certa, e e a do route.ts.
    """
    b = cenario["brutus"].id
    _vinculo(b, _barbeiro(b, "Zeca"), _servico(b))

    r = _pedir(client, barbeiroId="nao-existe")
    assert r.status_code == 200
    assert r.json()["servicos"] == []


def test_o_barbeiro_da_OUTRA_barbearia_nao_puxa_servico_nenhum(client, cenario):
    """O id existe — so nao naquele host. Sem o RLS, passar o id de um barbeiro
    da concorrente devolveria os servicos dela.
    """
    outro = cenario["dontony"].id
    barbeiro_de_la = _barbeiro(outro, "De la")
    _vinculo(outro, barbeiro_de_la, _servico(outro, nome="Barba"))

    b = cenario["brutus"].id
    _vinculo(b, _barbeiro(b, "Daqui"), _servico(b))

    assert _pedir(client, barbeiroId=barbeiro_de_la.id).json()["servicos"] == []


def test_ordena_por_ordem_e_nao_por_nome(client, cenario):
    """A ordem contraria o alfabeto de proposito: ordenado por nome, o teste
    passaria sem provar nada.
    """
    b = cenario["brutus"].id
    barbeiro = _barbeiro(b, "Zeca")
    for nome, ordem in (("Zapotes", 1), ("Abacate", 2)):
        _vinculo(b, barbeiro, _servico(b, nome=nome, ordem=ordem))

    nomes = [s["nome"] for s in _pedir(client).json()["servicos"]]
    assert nomes == ["Zapotes", "Abacate"]


def test_empate_de_ordem_desempata_por_nome(client, cenario):
    """Nada impede duas linhas com `ordem` 0, e do lado TypeScript a ordem
    delas sai de um `findMany` sem `orderBy` — indefinida. Uma lista que troca
    de ordem sozinha entre dois carregamentos e o tipo de coisa que se atribui
    ao navegador.
    """
    b = cenario["brutus"].id
    barbeiro = _barbeiro(b, "Zeca")
    for nome in ("Zapotes", "Abacate"):
        _vinculo(b, barbeiro, _servico(b, nome=nome, ordem=0))

    nomes = [s["nome"] for s in _pedir(client).json()["servicos"]]
    assert nomes == ["Abacate", "Zapotes"]


def test_o_rls_isola_uma_barbearia_da_outra(client, cenario):
    for slug, nome in (("brutus", "Corte"), ("dontony", "Barba")):
        b = cenario[slug].id
        _vinculo(b, _barbeiro(b, f"Barbeiro {slug}"), _servico(b, nome=nome))

    um = _pedir(client, "brutus.localhost").json()["servicos"]
    dois = _pedir(client, "dontony.localhost").json()["servicos"]

    assert [s["nome"] for s in um] == ["Corte"]
    assert [s["nome"] for s in dois] == ["Barba"]


def test_do_host_do_admin_da_404(client, cenario):
    assert _pedir(client, "admin.localhost").status_code == 404
