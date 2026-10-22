from datetime import datetime, timezone

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeDono
from app.services.custos import apagar_custo, lancar_custo, listar_custos
from app.services.resumo import periodo_pedido
from tenant.datas import dia_de_hoje


class LancarCustoSerializer(serializers.Serializer):
    nome = serializers.CharField(max_length=80, required=False, allow_null=True, allow_blank=True)
    # Teto de R$ 1 milhao: um zero a mais digitado sem querer nao vira um
    # numero que estoura o resto da tela.
    valorCentavos = serializers.IntegerField(min_value=1, max_value=100_000_000)


class CustosView(ExigeDono, APIView):
    """GET/POST /api/painel/custos — o GET aceita o mesmo `de`/`ate` do
    resumo, e cai no mesmo padrao quando vem torto."""

    mensagem_papel_insuficiente = "Só o dono vê os custos."

    def get(self, request):
        de, ate = periodo_pedido(
            request.query_params.get("de"),
            request.query_params.get("ate"),
            dia_de_hoje(datetime.now(timezone.utc)),
        )
        return Response(listar_custos(self.barbearia_id, de, ate))

    def post(self, request):
        entrada = LancarCustoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Coloca o valor do custo."}, status=422)
        d = entrada.validated_data
        novo_id = lancar_custo(self.barbearia_id, d.get("nome"), d["valorCentavos"])
        return Response({"id": novo_id}, status=201)


class CustoDetalheView(ExigeDono, APIView):
    """DELETE /api/painel/custos/<id> — para desfazer um lancamento errado."""

    mensagem_papel_insuficiente = "Só o dono vê os custos."

    def delete(self, request, id):
        if not apagar_custo(self.barbearia_id, id):
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
