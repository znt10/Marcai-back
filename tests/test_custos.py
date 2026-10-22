import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"


def _barbeiro(barbearia_id, papel="DONO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Zeca",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _h():
    return {"host": HOST, **CABECALHO}


def test_lancar_com_e_sem_nome_e_listar(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)

    r = client.post("/api/painel/custos", {"nome": " Lâminas ", "valorCentavos": 4590},
                    content_type="application/json", headers=_h())
    assert r.status_code == 201
    r = client.post("/api/painel/custos", {"valorCentavos": 1000},
                    content_type="application/json", headers=_h())
    assert r.status_code == 201

    r = client.get("/api/painel/custos", headers=_h())
    corpo = r.json()
    assert corpo["totalCentavos"] == 5590
    assert {c["valorCentavos"]: c["nome"] for c in corpo["custos"]} == {
        4590: "Lâminas", 1000: None,
    }


@pytest.mark.parametrize("corpo", [{}, {"nome": "Luz"}, {"valorCentavos": 0}, {"valorCentavos": -5}])
def test_valor_e_obrigatorio_e_positivo(client, cenario, corpo):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    r = client.post("/api/painel/custos", corpo, content_type="application/json", headers=_h())
    assert r.status_code == 422


def test_barbeiro_nao_ve_nem_lanca(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id, papel="BARBEIRO"), b.id)
    assert client.get("/api/painel/custos", headers=_h()).status_code == 403
    r = client.post("/api/painel/custos", {"valorCentavos": 100},
                    content_type="application/json", headers=_h())
    assert r.status_code == 403


def test_periodo_filtra_pelo_dia_do_lancamento(client, cenario):
    from tenant.models import Custo

    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    antigo = datetime.now(timezone.utc) - timedelta(days=60)
    Custo.objects.using("owner").create(barbearia_id=b.id, valor_centavos=700, criado_em=antigo)
    Custo.objects.using("owner").create(barbearia_id=b.id, valor_centavos=300)

    r = client.get("/api/painel/custos", headers=_h())
    assert r.json()["totalCentavos"] == 300


def test_apagar(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    novo = client.post("/api/painel/custos", {"valorCentavos": 100},
                       content_type="application/json", headers=_h()).json()["id"]
    assert client.delete(f"/api/painel/custos/{novo}", headers=_h()).status_code == 200
    assert client.delete(f"/api/painel/custos/{novo}", headers=_h()).status_code == 404


def test_custo_nao_vaza_entre_barbearias(cenario):
    from tenant.models import Custo

    Custo.objects.using("owner").create(barbearia_id=cenario["brutus"].id, valor_centavos=1)
    Custo.objects.using("owner").create(barbearia_id=cenario["dontony"].id, valor_centavos=2)
    with com_barbearia(cenario["brutus"].id):
        assert list(Custo.objects.values_list("valor_centavos", flat=True)) == [1]
    assert Custo.objects.count() == 0
