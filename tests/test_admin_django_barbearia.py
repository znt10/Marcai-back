"""Apagar e editar barbearia pelo admin do Django.

O primeiro uso de verdade (06/10/2026) foi apagar uma barbearia de teste, e
deu 500: `permission denied for table tenant_barbearia`. O admin do Django
escreve pela conexao `default` (`brutus_app`), que de proposito nao pode
mexer nessa tabela (o REVOKE da 0002). Quem pode e' a `admin`.

E so' trocar a conexao nao bastava para apagar: toda chave que aponta para a
barbearia e' RESTRICT, entao qualquer barbearia de verdade (que sempre tem
pelo menos o dono) ficaria em "nao da para apagar". Apagar a barbearia aqui
leva junto tudo o que e' dela, como o resto deste admin ja faz.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir

pytestmark = pytest.mark.django_db(
    databases=["default", "owner", "admin"], transaction=True
)

HOST = "admin.localhost"


def _entrar(client, escolhida):
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()
    nome = f"admin-{uuid.uuid4().hex[:8]}"
    User.objects.create_superuser(username=nome, email="", password="senha-de-teste")
    client.login(username=nome, password="senha-de-teste")
    r = client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": str(escolhida.id)},
        headers={"host": HOST},
    )
    assert r.status_code == 302


def _povoar(b):
    """Uma linha em cada tabela de tenant, como numa barbearia que ja rodou."""
    from tenant.models import (
        Agendamento, Barbeiro, BarbeiroServico, Bloqueio, Cliente,
        ConversaWhatsapp, HorarioTrabalho, ListaDoDiaEnviada,
        MensagemNaoEnviada, Servico, WhatsappInstancia,
    )

    o = "owner"
    barbeiro = Barbeiro.objects.using(o).filter(barbearia_id=b.id).first()
    servico = Servico.objects.using(o).create(
        barbearia_id=b.id, nome="Corte", duracao_minima_min=30, duracao_sugerida_min=30,
    )
    BarbeiroServico.objects.using(o).create(
        barbearia_id=b.id, barbeiro=barbeiro, servico=servico, duracao_min=30,
    )
    HorarioTrabalho.objects.using(o).create(
        barbearia_id=b.id, barbeiro=barbeiro, dia_semana=1, minutos_inicio=540, minutos_fim=1080,
    )
    Bloqueio.objects.using(o).create(
        barbearia_id=b.id, barbeiro=barbeiro, motivo="ALMOCO", repete_semanalmente=True,
        dia_semana=1, minutos_inicio=720, minutos_fim=780,
    )
    cliente = Cliente.objects.using(o).create(barbearia_id=b.id, nome="Cli", whatsapp="11987654321")
    inicio = datetime.now(timezone.utc) + timedelta(days=2)
    Agendamento.objects.using(o).create(
        barbearia_id=b.id, codigo=uuid.uuid4().hex[:10], barbeiro=barbeiro, cliente=cliente,
        servico=servico, servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )
    WhatsappInstancia.objects.using(o).create(barbearia_id=b.id, nome=f"inst-{b.slug}")
    MensagemNaoEnviada.objects.using(o).create(barbearia_id=b.id, tipo="CONFIRMACAO", cliente_nome="Cli")
    ConversaWhatsapp.objects.using(o).create(barbearia_id=b.id, whatsapp="11987654321")
    ListaDoDiaEnviada.objects.using(o).create(
        barbearia_id=b.id, barbeiro=barbeiro, dia=date.today(), mensagem_id="m", remote_jid="j",
    )


def _linhas_de(barbearia_id) -> dict[str, int]:
    """Quantas linhas a barbearia tem em cada tabela que aponta para ela, lido
    como `owner` (fora do RLS) para nada ficar escondido."""
    from tenant.models import Barbearia

    return {
        rel.related_model.__name__: rel.related_model.objects.using("owner")
        .filter(barbearia_id=barbearia_id).count()
        for rel in Barbearia._meta.related_objects
    }


@pytest.fixture(autouse=True)
def _sem_evolution():
    with patch("app.services.admin_barbearias.desligar_na_evolution") as desligar:
        yield desligar


def test_apagar_barbearia_sem_nada_dentro(client, cenario):
    from tenant.models import Barbearia, Barbeiro

    vazia = Barbearia.objects.using("owner").create(
        slug="vazia", nome="Vazia", endereco="x", whatsapp_contato="11999998888", plano="SEM_ZAP",
    )
    _entrar(client, cenario["brutus"])

    r = client.post(f"/admin/django/tenant/barbearia/{vazia.id}/delete/", {"post": "yes"},
                    headers={"host": HOST})

    assert r.status_code == 302
    assert not Barbearia.objects.using("owner").filter(id=vazia.id).exists()
    assert Barbeiro.objects.using("owner").filter(barbearia_id=cenario["brutus"].id).exists()


def test_apagar_barbearia_leva_tudo_dela_e_nada_da_outra(client, cenario):
    """Escolhida a OUTRA barbearia no seletor, que e' o caso traicoeiro: o RLS
    da requisicao esconde as linhas da que vai ser apagada."""
    from tenant.models import Barbearia

    b, d = cenario["brutus"], cenario["dontony"]
    _povoar(b)
    _povoar(d)
    antes_da_outra = _linhas_de(d.id)
    _entrar(client, d)

    r = client.post(f"/admin/django/tenant/barbearia/{b.id}/delete/", {"post": "yes"},
                    headers={"host": HOST})

    assert r.status_code == 302
    assert not Barbearia.objects.using("owner").filter(id=b.id).exists()
    assert set(_linhas_de(b.id).values()) == {0}
    assert _linhas_de(d.id) == antes_da_outra


def test_a_confirmacao_diz_o_que_vai_junto(client, cenario):
    b = cenario["brutus"]
    _povoar(b)
    _entrar(client, cenario["dontony"])

    r = client.get(f"/admin/django/tenant/barbearia/{b.id}/delete/", headers={"host": HOST})

    assert r.status_code == 200
    corpo = r.content.decode()
    assert "Cannot delete" not in corpo
    assert "1 agendamento" in corpo
    assert "1 cliente" in corpo


def test_apagar_em_massa_pela_lista(client, cenario):
    from tenant.models import Barbearia

    b, d = cenario["brutus"], cenario["dontony"]
    _povoar(b)
    _povoar(d)
    _entrar(client, b)

    r = client.post(
        "/admin/django/tenant/barbearia/",
        {"action": "delete_selected", "_selected_action": [str(b.id), str(d.id)], "post": "yes"},
        headers={"host": HOST},
    )

    assert r.status_code == 302
    assert not Barbearia.objects.using("owner").exists()


def test_apagar_a_barbearia_escolhida_volta_ao_seletor(client, cenario):
    """Sem isto a sessao continuaria apontando para um id que nao existe mais,
    e o admin mostraria toda lista vazia sem dizer por que."""
    b = cenario["brutus"]
    _entrar(client, b)

    client.post(f"/admin/django/tenant/barbearia/{b.id}/delete/", {"post": "yes"},
                headers={"host": HOST})

    r = client.get("/admin/django/tenant/cliente/", headers={"host": HOST})
    assert r.status_code == 302
    assert r["Location"] == "/admin/django/escolher-barbearia"


def test_apagar_desliga_a_instancia_na_evolution(client, cenario, _sem_evolution):
    b = cenario["brutus"]
    _povoar(b)
    _entrar(client, b)

    client.post(f"/admin/django/tenant/barbearia/{b.id}/delete/", {"post": "yes"},
                headers={"host": HOST})

    _sem_evolution.assert_called_once_with("inst-brutus")


def test_editar_barbearia_pelo_admin(client, cenario):
    from tenant.models import Barbearia

    b = cenario["brutus"]
    _entrar(client, b)

    r = client.post(
        f"/admin/django/tenant/barbearia/{b.id}/change/",
        {
            "id": str(b.id), "slug": "brutus", "nome": "Brutus Novo", "endereco": "Rua Aurora, 88",
            "horario_resumo": "seg a sab, 9h as 19h", "whatsapp_contato": "11999998888", "plano": "SEM_ZAP",
            "ativo": "on", "criado_em_0": "2026-08-11", "criado_em_1": "09:00:00",
        },
        headers={"host": HOST},
    )

    assert r.status_code == 302
    assert Barbearia.objects.using("owner").get(id=b.id).nome == "Brutus Novo"


def test_editar_barbearia_sem_horario_resumo(client, cenario):
    """Barbearia recem-criada nao tem horario (o dono e' quem preenche); o
    admin tem de deixar trocar o WhatsApp mesmo assim, e o vazio fica nulo."""
    from tenant.models import Barbearia

    b = cenario["brutus"]
    _entrar(client, b)

    r = client.post(
        f"/admin/django/tenant/barbearia/{b.id}/change/",
        {
            "id": str(b.id), "slug": "brutus", "nome": "Brutus", "endereco": "Rua Aurora, 88",
            "horario_resumo": "", "whatsapp_contato": "13988771112", "plano": "SEM_ZAP",
            "ativo": "on", "criado_em_0": "2026-08-11", "criado_em_1": "09:00:00",
        },
        headers={"host": HOST},
    )

    assert r.status_code == 302
    salva = Barbearia.objects.using("owner").get(id=b.id)
    assert salva.whatsapp_contato == "13988771112"
    assert salva.horario_resumo is None


def test_toda_tabela_que_aponta_para_barbearia_sai_junto():
    """Uma tabela de tenant nova, esquecida na ordem de apagar, faria o apagar
    voltar a estourar no banco. Este teste e' quem lembra."""
    from app.services.admin_barbearias import ORDEM_DE_APAGAR
    from tenant.models import Barbearia

    apontam = {rel.related_model for rel in Barbearia._meta.related_objects}
    assert apontam == set(ORDEM_DE_APAGAR)
