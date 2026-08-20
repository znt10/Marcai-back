import uuid

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


def test_get_devolve_os_sete_dias_com_null_onde_esta_fechado(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import HorarioTrabalho

    HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
        dia_semana=2, minutos_inicio=540, minutos_fim=1080,
    )

    r = client.get("/api/painel/expediente", {"barbeiroId": barbeiro.id}, headers={"host": host})
    assert r.status_code == 200
    expediente = r.json()["expediente"]
    assert len(expediente) == 7
    assert expediente[2] == {"diaSemana": 2, "minutosInicio": 540, "minutosFim": 1080}
    assert expediente[0] == {"diaSemana": 0, "minutosInicio": None, "minutosFim": None}


def test_get_barbeiro_pedindo_o_do_colega_e_404(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    r = client.get("/api/painel/expediente", {"barbeiroId": colega.id}, headers={"host": host})
    assert r.status_code == 404


def test_put_cria_e_depois_atualiza_o_mesmo_dia(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r1 = client.put(
        "/api/painel/expediente",
        {"diaSemana": 1, "minutosInicio": 540, "minutosFim": 1080},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r1.status_code == 200

    r2 = client.put(
        "/api/painel/expediente",
        {"diaSemana": 1, "minutosInicio": 480, "minutosFim": 1020},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r2.status_code == 200

    from tenant.models import HorarioTrabalho

    linhas = HorarioTrabalho.objects.using("owner").filter(barbeiro_id=barbeiro.id, dia_semana=1)
    assert linhas.count() == 1
    assert linhas.first().minutos_inicio == 480


def test_put_fim_antes_do_inicio_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.put(
        "/api/painel/expediente",
        {"diaSemana": 1, "minutosInicio": 1080, "minutosFim": 540},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_put_minutos_nao_inteiro_e_422(client, cenario):
    """`z.number()` no front aceita qualquer numero — quem recusa fracionado
    e' `jornada_valida`, com a mensagem propria."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.put(
        "/api/painel/expediente",
        {"diaSemana": 1, "minutosInicio": 540.5, "minutosFim": 1080},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422
    assert r.json()["erro"] == "Horário fora do dia."


def test_delete_apaga_a_linha_e_e_idempotente(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import HorarioTrabalho

    HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
        dia_semana=3, minutos_inicio=540, minutos_fim=1080,
    )

    # `client.delete(path, data)` manda `data` como CORPO, nao query string —
    # diferente do `.get()`. A query precisa ir na propria URL.
    url = f"/api/painel/expediente?barbeiroId={barbeiro.id}&diaSemana=3"

    r1 = client.delete(url, headers={"host": host, **CABECALHO})
    assert r1.status_code == 200
    assert not HorarioTrabalho.objects.using("owner").filter(
        barbeiro_id=barbeiro.id, dia_semana=3
    ).exists()

    # Apagar de novo (ja nao existe) continua respondendo ok — o motor trata
    # ausencia como "fechado", nao ha segundo estado para "ja apagado".
    r2 = client.delete(url, headers={"host": host, **CABECALHO})
    assert r2.status_code == 200


def test_dono_mexe_no_expediente_de_qualquer_um(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, dono, b.id)

    r = client.put(
        "/api/painel/expediente",
        {"barbeiroId": colega.id, "diaSemana": 1, "minutosInicio": 540, "minutosFim": 1080},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import HorarioTrabalho

    assert HorarioTrabalho.objects.using("owner").filter(barbeiro_id=colega.id).exists()
