from datetime import datetime, timezone

from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.api.v1.serializers.agendamentos import CriarAgendamentoSerializer
from app.services.agendamentos import ErroCliente, cancelar, eh_sobreposicao, marcar
from app.services.autorizacao import filtro_do_barbeiro
from app.services.mensagens import msg_cancelamento_pela_barbearia, msg_confirmacao
from app.services.whatsapp import enviar_texto
from tenant.telefone import normalizar
from tenant.identidade import como_uuid


class AgendamentosPainelView(ExigeSessao, APIView):
    """POST /api/painel/agendamentos — marcar cliente na mao."""

    def post(self, request):
        entrada = CriarAgendamentoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche nome e WhatsApp."}, status=422)
        d = entrada.validated_data

        whatsapp = normalizar(d["whatsapp"])
        if not whatsapp:
            return Response({"erro": "Confere o WhatsApp — parece faltar dígito."}, status=422)

        # O `barbeiroId` vem do CORPO como texto e o filtro carrega
        # `uuid.UUID` (a sessao converte na entrada). Comparar os dois crus da
        # sempre "diferente", e o sintoma e' caro: TODO agendamento pelo painel
        # vira 404, inclusive o do proprio barbeiro na propria agenda.
        alvo = como_uuid(d["barbeiroId"])
        if alvo is None:
            return Response(NAO_ENCONTRADO, status=404)

        # Marcar na agenda de OUTRO barbeiro e' 404, nao 403: 403
        # confirmaria que aquele barbeiro existe nesta barbearia.
        filtro = filtro_do_barbeiro(self.sessao)
        if filtro.get("barbeiro_id") and filtro["barbeiro_id"] != alvo:
            return Response(NAO_ENCONTRADO, status=404)

        agora = datetime.now(timezone.utc)
        try:
            criado = marcar(
                barbearia_id=self.barbearia_id, barbeiro_id=alvo,
                servico_id=d["servicoId"], inicio=d["inicio"],
                nome=d["nome"], whatsapp=whatsapp, agora=agora,
            )
        except ErroCliente as e:
            return Response({"erro": e.mensagem}, status=e.status)
        except IntegrityError as e:
            if eh_sobreposicao(e):
                return Response({"erro": "Esse horário acabou de ser pego."}, status=409)
            raise

        # Fire-and-forget, DEPOIS do commit: falha de WhatsApp nao desfaz nada.
        link = f"{request.headers.get('origin', '')}/agendamento/{criado['codigo']}"
        enviar_texto(
            whatsapp,
            msg_confirmacao(
                cliente_nome=d["nome"], barbeiro_nome=criado["barbeiro_nome"],
                servico_nome=criado["servico_nome"], inicio=criado["inicio"],
                endereco=request.barbearia.endereco, link=link,
            ),
        )
        return Response({"codigo": criado["codigo"]}, status=201)


class AgendamentoCancelarView(ExigeSessao, APIView):
    """POST /api/painel/agendamentos/<id>/cancelar"""

    def post(self, request, id):
        filtro = filtro_do_barbeiro(self.sessao)
        cancelado = cancelar(self.barbearia_id, id, filtro.get("barbeiro_id"))
        if cancelado is None:
            return Response(NAO_ENCONTRADO, status=404)

        enviar_texto(
            cancelado["cliente_whatsapp"],
            msg_cancelamento_pela_barbearia(
                cliente_nome=cancelado["cliente_nome"], barbeiro_nome=cancelado["barbeiro_nome"],
                servico_nome=cancelado["servico_nome"], inicio=cancelado["inicio"],
                endereco=request.barbearia.endereco,
            ),
        )
        return Response({"ok": True})
