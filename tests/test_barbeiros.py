import uuid

import pytest
from fabricas import criar_barbeiro

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


def _vinculo(barbearia_id, barbeiro, servico, ativo=True):
    from tenant.models import BarbeiroServico

    return BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id,
        servico_id=servico.id,
        barbearia_id=barbearia_id,
        duracao_min=30,
        ativo=ativo,
    )


def _barbeiro(barbearia_id, nome, ordem=0, ativo=True):
    from tenant.models import Barbeiro

    return criar_barbeiro(
        id=str(uuid.uuid4()),
        barbearia_id=barbearia_id,
        nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
        ativo=ativo,
        ordem=ordem,
    )


def _pedir(client, host="brutus.localhost"):
    return client.get("/api/barbeiros", headers={"host": host})


def test_lista_quem_tem_servico_ativo(client, cenario):
    b = cenario["brutus"]
    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    _vinculo(b.id, barbeiro, _servico(b.id))

    r = _pedir(client)
    assert r.status_code == 200
    assert [x["nome"] for x in r.json()["barbeiros"]] == [barbeiro.nome]


def test_o_envelope_e_os_campos_sao_os_mesmos_do_next(client, cenario):
    """O contrato nao pode mudar na travessia: a tela ja le `r.barbeiros` e
    espera id, nome e fotoUrl em camelCase. E nada alem disso — whatsapp e
    senhaHash nao podem aparecer (§9.1).
    """
    b = cenario["brutus"]
    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    _vinculo(b.id, barbeiro, _servico(b.id))

    corpo = _pedir(client).json()
    assert set(corpo) == {"barbeiros"}
    assert set(corpo["barbeiros"][0]) == {"id", "nome", "fotoUrl"}


def test_sem_vinculo_nenhum_o_barbeiro_nao_aparece(client, cenario):
    """Aparecer na lista e nao ter o que agendar e um beco sem saida."""
    assert _pedir(client).json()["barbeiros"] == []


def test_vinculo_ativo_com_servico_INATIVO_nao_conta(client, cenario):
    """A metade da regra que ja falhou no lado TypeScript: com o servico
    desativado na barbearia inteira, o vinculo continua ativo e o barbeiro
    continuava aparecendo — com a tela seguinte vazia.
    """
    b = cenario["brutus"]
    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    _vinculo(b.id, barbeiro, _servico(b.id, ativo=False))

    assert _pedir(client).json()["barbeiros"] == []


def test_vinculo_INATIVO_com_servico_ativo_nao_conta(client, cenario):
    b = cenario["brutus"]
    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    _vinculo(b.id, barbeiro, _servico(b.id), ativo=False)

    assert _pedir(client).json()["barbeiros"] == []


def test_barbeiro_inativo_nao_aparece(client, cenario):
    b = cenario["brutus"]
    servico = _servico(b.id)
    desligado = _barbeiro(b.id, "Desligado", ativo=False)
    _vinculo(b.id, desligado, servico)

    assert _pedir(client).json()["barbeiros"] == []


def test_ordena_por_ordem_e_nao_por_nome(client, cenario):
    """Se ordenasse por nome, 'Ana' viria antes de 'Zeca' e o teste passaria
    sem provar nada — por isso a ordem contraria o alfabeto de proposito.
    """
    b = cenario["brutus"]
    servico = _servico(b.id)
    for nome, ordem in (("Zeca", 1), ("Ana", 2)):
        _vinculo(b.id, _barbeiro(b.id, nome, ordem=ordem), servico)

    nomes = [x["nome"] for x in _pedir(client).json()["barbeiros"]]
    assert nomes[:2] == ["Zeca", "Ana"]


def test_o_rls_isola_uma_barbearia_da_outra(client, cenario):
    """O teste que vale: cada host so ve a propria equipe. Sem RLS escopado, a
    lista viria somada e ninguem notaria ate um cliente ver o barbeiro de
    outra barbearia.
    """
    from tenant.models import Barbeiro

    for slug in ("brutus", "dontony"):
        b = cenario[slug]
        barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
        _vinculo(b.id, barbeiro, _servico(b.id))

    um = _pedir(client, "brutus.localhost").json()["barbeiros"]
    dois = _pedir(client, "dontony.localhost").json()["barbeiros"]

    assert [x["nome"] for x in um] == ["Barbeiro da Brutus"]
    assert [x["nome"] for x in dois] == ["Barbeiro da Dom Tony"]


def test_do_host_do_admin_a_rota_de_tenant_da_404_e_nao_500(client, cenario):
    """Item 3 do card: o middleware poe request.barbearia = None no host do
    admin. Sem o mixin ExigeTenant isto seria AttributeError -> 500.
    """
    r = _pedir(client, "admin.localhost")
    assert r.status_code == 404


def test_o_crivo_do_painel_recusa_no_django(client, cenario):
    """Item 2 do card. Nenhuma rota de painel atravessou ainda, entao o crivo
    nega — mas ele EXISTE, e e isso que impede a primeira rota de painel de
    nascer aberta quando entrar no MIGRADAS.
    """
    r = client.get("/api/painel/agenda", headers={"host": "brutus.localhost"})
    assert r.status_code == 401
