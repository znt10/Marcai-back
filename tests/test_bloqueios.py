import uuid
from datetime import datetime, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from fabricas import criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return criar_barbeiro(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.usuario_id, bid=barbearia_id, papel=barbeiro.usuario.papel, tv=0)
    return host


def test_post_bloqueio_semanal(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.post(
        "/api/painel/bloqueios",
        {
            "motivo": "ALMOCO", "repeteSemanalmente": True,
            "diaSemana": 2, "minutosInicio": 720, "minutosFim": 780,
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").get(id=r.json()["id"])
    assert bloqueio.dia_semana == 2 and bloqueio.motivo == "ALMOCO"


def test_post_bloqueio_pontual(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {"motivo": "PESSOAL", "repeteSemanalmente": False, "inicio": inicio, "fim": fim},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201


def test_post_com_os_dois_formatos_juntos_e_422(client, cenario):
    """O motor le um formato OU o outro — os dois juntos gravariam uma linha
    de interpretacao ambigua."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {
            "motivo": "OUTRO", "repeteSemanalmente": False,
            "diaSemana": 2, "inicio": inicio, "fim": fim,
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422
    assert "Escolhe" in r.json()["erro"]


def test_post_pontual_com_fim_antes_do_inicio_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {"motivo": "OUTRO", "repeteSemanalmente": False, "inicio": inicio, "fim": fim},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_delete_apaga(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(
        f"/api/painel/bloqueios/{bloqueio.id}", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200
    assert not Bloqueio.objects.using("owner").filter(id=bloqueio.id).exists()


def test_delete_do_bloqueio_do_colega_e_404(client, cenario):
    """Reconferencia DEPOIS de carregar: forjar o id do bloqueio de um colega
    devolve 404, nao 403 — 403 confirmaria que o registro existe."""
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    from tenant.models import Bloqueio

    bloqueio_do_colega = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=colega.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(
        f"/api/painel/bloqueios/{bloqueio_do_colega.id}", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404
    assert Bloqueio.objects.using("owner").filter(id=bloqueio_do_colega.id).exists()


def test_dono_apaga_bloqueio_de_qualquer_um(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, dono, b.id)

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=colega.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(f"/api/painel/bloqueios/{bloqueio.id}", headers={"host": host, **CABECALHO})
    assert r.status_code == 200


def test_delete_id_inexistente_e_404(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.delete("/api/painel/bloqueios/nao-existe", headers={"host": host, **CABECALHO})
    assert r.status_code == 404
