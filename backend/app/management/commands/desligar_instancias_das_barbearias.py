from django.core.management.base import BaseCommand

from app.services.whatsapp_instancias import apagar_instancia
from tenant.models import Barbearia, WhatsappInstancia


class Command(BaseCommand):
    """Etapa 1 do numero central (spec 2026-10-06): tira a Evolution do
    numero de toda barbearia.

    Roda UMA vez, no conteiner `api`, depois do deploy. `apagar_instancia`
    faz logout (o celular da barbearia deixa de listar o aparelho conectado),
    apaga a instancia na Evolution e apaga a linha. Rodar de novo nao acha
    nada.

    Le as instancias pela conexao `owner`, de todos os tenants de uma vez —
    o caso que a politica `owner_irrestrito` existe para servir.
    """

    help = "Desconecta e apaga a instancia da Evolution de toda barbearia."

    def handle(self, *args, **opcoes):
        ids = list(
            WhatsappInstancia.objects.using("owner").values_list("barbearia_id", flat=True)
        )
        for barbearia in Barbearia.objects.using("owner").filter(id__in=ids):
            apagar_instancia(barbearia)
            self.stdout.write(f"desligada: {barbearia.nome} ({barbearia.slug})")
        self.stdout.write(f"{len(ids)} instancia(s) desligada(s)")
