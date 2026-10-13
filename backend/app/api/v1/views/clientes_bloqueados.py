from collections import defaultdict
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeDono, ExigeSessao
from app.services import lista_do_dia
from app.services.autorizacao import filtro_do_barbeiro
from app.services.clientes_bloqueados import bloquear, desbloquear, listar, previa


class BloquearClienteView(ExigeSessao, APIView):
    """GET/POST /api/painel/agendamentos/<id>/bloquear-cliente — a partir de
    um horario da agenda, como o cancelar. Qualquer um da equipe; o barbeiro
    so' alcanca os horarios dele (o do colega e' 404)."""

    def get(self, request, id):
        r = previa(
            self.barbearia_id, id, filtro_do_barbeiro(self.sessao).get("barbeiro_id"),
            datetime.now(timezone.utc),
        )
        return Response(r) if r is not None else Response(NAO_ENCONTRADO, status=404)

    def post(self, request, id):
        agora = datetime.now(timezone.utc)
        cancelados = bloquear(
            self.barbearia_id, id, filtro_do_barbeiro(self.sessao).get("barbeiro_id"),
            self.sessao["sub"], agora,
        )
        if cancelados is None:
            return Response(NAO_ENCONTRADO, status=404)
        # Sem WhatsApp ao cliente (decisao do dono). A lista do dia de cada
        # barbeiro afetado sai refeita, se o cancelado era de hoje.
        por_barbeiro = defaultdict(list)
        for barbeiro_id, agendamento_id, inicio in cancelados:
            por_barbeiro[barbeiro_id].append((agendamento_id, inicio))
        for barbeiro_id, pares in por_barbeiro.items():
            lista_do_dia.avisar_mudanca(self.barbearia_id, barbeiro_id, agora, cancelados=pares)
        return Response({"ok": True, "cancelados": len(cancelados)})


class ClientesBloqueadosView(ExigeDono, APIView):
    """GET /api/painel/clientes/bloqueados"""

    mensagem_papel_insuficiente = "Só o dono vê os clientes bloqueados."

    def get(self, request):
        return Response(listar(self.barbearia_id))


class DesbloquearClienteView(ExigeDono, APIView):
    """POST /api/painel/clientes/<id>/desbloquear"""

    mensagem_papel_insuficiente = "Só o dono vê os clientes bloqueados."

    def post(self, request, id):
        if not desbloquear(self.barbearia_id, id):
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
