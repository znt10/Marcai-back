from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.api.v1.serializers.expediente import CriarBloqueioSerializer
from app.services.autorizacao import alvo_do_barbeiro, filtro_do_barbeiro
from app.services.agendamentos import cancelar as cancelar_agendamento
from app.services.bloqueios import apagar_bloqueio, criar_bloqueio, folga_sobreposta
from app.services.conflitos import agendamentos_no_bloqueio
from app.services.horarios import bloqueio_valido
from app.services.mensagens import msg_cancelamento_pela_barbearia
from app.services.whatsapp import enviar_texto


class BloqueiosView(ExigeSessao, APIView):
    """POST /api/painel/bloqueios"""

    def post(self, request):
        entrada = CriarBloqueioSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o bloqueio."}, status=422)
        d = entrada.validated_data

        barbeiro_id = alvo_do_barbeiro(self.sessao, d.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        campos = {
            "motivo": d["motivo"],
            "observacao": d.get("observacao"),
            "repete_semanalmente": d["repeteSemanalmente"],
            "dia_semana": d.get("diaSemana"),
            "minutos_inicio": d.get("minutosInicio"),
            "minutos_fim": d.get("minutosFim"),
            "inicio": d.get("inicio"),
            "fim": d.get("fim"),
        }
        recusa = bloqueio_valido(
            repete_semanalmente=campos["repete_semanalmente"],
            dia_semana=campos["dia_semana"],
            minutos_inicio=campos["minutos_inicio"],
            minutos_fim=campos["minutos_fim"],
            inicio=campos["inicio"],
            fim=campos["fim"],
        )
        if recusa:
            return Response({"erro": recusa}, status=422)

        # Folga em cima de folga e' recusado de saida, antes de olhar
        # agendamento: e' erro de preenchimento, nao decisao de produto.
        empilhada = folga_sobreposta(self.barbearia_id, barbeiro_id, campos)
        if empilhada:
            return Response({"erro": empilhada}, status=422)

        # Quem ja esta marcado dentro do horario que a pessoa quer fechar.
        # Perguntado ANTES de criar: bloquear por cima de horario vendido
        # deixava o cliente esperando por um corte que nao ia acontecer, e
        # cabia ao barbeiro achar cada um na lista de conflitos e cancelar na
        # mao.
        agora = datetime.now(timezone.utc)
        pegos = agendamentos_no_bloqueio(self.barbearia_id, barbeiro_id, campos, agora)

        # Sem `cancelarConflitos`, a resposta e' uma PERGUNTA, nao um erro: o
        # bloqueio nao e' criado e a tela mostra quem cairia. Cancelamento e'
        # irreversivel e o WhatsApp sai na hora — um toque errado no horario
        # nao pode custar a tarde de tres clientes.
        if pegos and not request.data.get("cancelarConflitos"):
            return Response({"erro": "conflito", "conflitos": pegos}, status=409)

        novo_id = criar_bloqueio(self.barbearia_id, barbeiro_id, campos)

        # DEPOIS de criar o bloqueio: se o cancelamento falhar no meio, o
        # horario continua fechado — o contrario deixaria clientes cancelados
        # e a agenda aberta de novo.
        cancelados = 0
        for c in pegos:
            dados = cancelar_agendamento(self.barbearia_id, c["id"], barbeiro_id)
            if dados is None:
                continue
            cancelados += 1
            # Fire-and-forget, igual ao resto: WhatsApp fora do ar nao desfaz
            # um cancelamento que ja' valeu.
            enviar_texto(
                dados["cliente_whatsapp"],
                msg_cancelamento_pela_barbearia(
                    cliente_nome=dados["cliente_nome"],
                    barbeiro_nome=dados["barbeiro_nome"],
                    servico_nome=dados["servico_nome"],
                    inicio=dados["inicio"],
                    endereco=request.barbearia.endereco,
                ),
            )
        return Response({"id": novo_id, "cancelados": cancelados}, status=201)


class BloqueioDetalheView(ExigeSessao, APIView):
    """DELETE /api/painel/bloqueios/<id>"""

    def delete(self, request, id):
        filtro = filtro_do_barbeiro(self.sessao)
        apagado = apagar_bloqueio(self.barbearia_id, id, filtro.get("barbeiro_id"))
        if not apagado:
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
