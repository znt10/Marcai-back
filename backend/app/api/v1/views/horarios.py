import re
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.horarios import DiaSerializer
from app.services.agenda import dias_com_horarios, dias_com_vaga
from app.services.servicos import QUALQUER

DIA = re.compile(r"\d{4}-\d{2}-\d{2}")
MES = re.compile(r"\d{4}-\d{2}")


def _agora() -> datetime:
    """Um instante so por pedido, lido AQUI e passado adiante.

    Um mes de calendario faz 31 chamadas ao motor. Se cada uma lesse o relogio,
    a virada da meia-noite no meio do calculo poderia marcar o dia 1 como
    passado e o dia 2 como futuro na mesma resposta.
    """
    return datetime.now(timezone.utc)


class HorariosView(ExigeTenant, APIView):
    """GET /api/horarios?servicoId=…&barbeiroId=…&de=…&dias=…"""

    def get(self, request):
        p = request.query_params
        servico_id = p.get("servicoId")
        if not servico_id:
            # A mensagem e a do route.ts, com acento: ela aparece na tela.
            return Response({"erro": "Escolhe o serviço primeiro."}, status=400)

        de = p.get("de")
        if de and not DIA.fullmatch(de):
            # O route.ts NAO valida `de`, e la um valor torto vira uma data
            # invalida que se propaga como texto ("Invalid Date") ate a tela.
            # Aqui viraria ValueError -> 500. 400 e a resposta honesta, e e a
            # unica das tres que diz o que aconteceu.
            return Response({"erro": "Data inválida."}, status=400)

        dias = dias_com_horarios(
            self.barbearia_id,
            p.get("barbeiroId") or QUALQUER,
            servico_id,
            de,
            _inteiro(p.get("dias")),
            _agora(),
        )
        return Response({"dias": DiaSerializer(dias, many=True).data})


class DiasComVagaView(ExigeTenant, APIView):
    """GET /api/dias-com-vaga?servicoId=…&mes=YYYY-MM&barbeiroId=…

    Alimenta o mini-calendario: quais dias do mes tem ao menos um horario.
    """

    def get(self, request):
        p = request.query_params
        servico_id = p.get("servicoId")
        mes = p.get("mes")
        if not servico_id or not mes or not MES.fullmatch(mes):
            return Response({"erro": "Parâmetros inválidos."}, status=400)
        # O regex garante a FORMA, nao o valor: `2026-13` passa por ele e
        # estouraria no calendario. 12 meses e um numero que nao muda.
        if not 1 <= int(mes.split("-")[1]) <= 12:
            return Response({"erro": "Parâmetros inválidos."}, status=400)

        return Response(
            {
                "dias": dias_com_vaga(
                    self.barbearia_id,
                    p.get("barbeiroId") or QUALQUER,
                    servico_id,
                    mes,
                    _agora(),
                )
            }
        )


def _inteiro(bruto: str | None) -> int | None:
    """None quando nao da para ler, para o servico aplicar o padrao.

    DIVERGE do route.ts de proposito, e vale saber por que. La o `Number('abc')`
    da NaN, o `Math.min(NaN, 60)` da NaN, e o laco `i < NaN` nao roda nenhuma
    vez — ou seja, `?dias=abc` responde 200 com a agenda VAZIA. Agenda vazia e
    a pior resposta errada possivel nesta tela: ela e indistinguivel de uma
    barbearia sem nenhum horario livre, e o cliente vai embora achando que nao
    ha vaga. Cair no padrao de dois dias mostra menos do que foi pedido, o que
    e visivelmente diferente de mostrar nada.
    """
    if bruto is None:
        return None
    try:
        return int(bruto)
    except ValueError:
        return None
