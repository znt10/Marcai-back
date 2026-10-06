"""O comando de uma vez so' da etapa 1: tira a Evolution do numero de toda
barbearia."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _sem_evolution(monkeypatch):
    # Sem URL, `apagar_instancia` pula as chamadas de rede e so' apaga a
    # linha — o que interessa aqui e' que TODA linha some.
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def test_apaga_a_instancia_de_toda_barbearia_e_e_idempotente(cenario):
    from tenant.models import WhatsappInstancia

    for b in cenario.values():
        WhatsappInstancia.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, nome=f"marcai-{b.id}",
        )

    saida = StringIO()
    call_command("desligar_instancias_das_barbearias", stdout=saida)
    assert WhatsappInstancia.objects.using("owner").count() == 0
    assert "2 instancia(s) desligada(s)" in saida.getvalue()

    saida = StringIO()
    call_command("desligar_instancias_das_barbearias", stdout=saida)
    assert "0 instancia(s) desligada(s)" in saida.getvalue()
