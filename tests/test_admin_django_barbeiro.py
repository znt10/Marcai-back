"""Apagar barbeiro pelo admin do Django.

O primeiro barbeiro de teste em producao (07/10/2026) nao saia: desativado e
com os agendamentos apagados, o admin ainda dizia "Cannot delete barbeiro" por
causa da lista do dia que ele tinha recebido ("lista de 2026-10-06 (...)").
Essa linha so' existe para a Evolution conseguir apagar a mensagem da lista;
ela nao e' historico de ninguem, e nao tem tela no admin para ser apagada a
mao. Ela vai junto com o barbeiro.

O que continua segurando o barbeiro e' agendamento: esse e' historico de
cliente.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

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
    client.post(
        "/admin/django/escolher-barbearia",
        {"barbearia_id": str(escolhida.id)},
        headers={"host": HOST},
    )


def _barbeiro_de_teste(b):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        barbearia_id=b.id, nome="Teste", whatsapp="83988010990", ativo=False,
    )


def _lista(b, barbeiro):
    from tenant.models import ListaDoDiaEnviada

    ListaDoDiaEnviada.objects.using("owner").create(
        barbearia_id=b.id, barbeiro=barbeiro, dia=date(2026, 10, 6),
        mensagem_id="3EB0TESTE", remote_jid="5583988010990@s.whatsapp.net",
    )


def test_a_lista_do_dia_recebida_nao_segura_o_barbeiro(client, cenario):
    from tenant.models import Barbeiro, ListaDoDiaEnviada

    b = cenario["brutus"]
    teste = _barbeiro_de_teste(b)
    _lista(b, teste)
    _entrar(client, b)

    r = client.post(f"/admin/django/tenant/barbeiro/{teste.id}/delete/", {"post": "yes"},
                    headers={"host": HOST})

    assert r.status_code == 302
    assert not Barbeiro.objects.using("owner").filter(id=teste.id).exists()
    assert not ListaDoDiaEnviada.objects.using("owner").filter(barbeiro_id=teste.id).exists()


def test_agendamento_continua_segurando_o_barbeiro(client, cenario):
    from tenant.models import Agendamento, Barbeiro, Cliente, Servico

    b = cenario["brutus"]
    teste = _barbeiro_de_teste(b)
    servico = Servico.objects.using("owner").create(
        barbearia_id=b.id, nome="Corte", duracao_minima_min=10, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(barbearia_id=b.id, nome="Cli", whatsapp="83988010991")
    inicio = datetime.now(timezone.utc) - timedelta(days=3)
    Agendamento.objects.using("owner").create(
        barbearia_id=b.id, codigo=uuid.uuid4().hex[:10], barbeiro=teste, cliente=cliente,
        servico=servico, servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )
    _entrar(client, b)

    r = client.post(f"/admin/django/tenant/barbeiro/{teste.id}/delete/", {"post": "yes"},
                    headers={"host": HOST})

    assert r.status_code == 200
    assert "Cannot delete" in r.content.decode()
    assert Barbeiro.objects.using("owner").filter(id=teste.id).exists()
