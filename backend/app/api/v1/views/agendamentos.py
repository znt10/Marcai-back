from datetime import datetime, timezone

from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.agendamentos import (
    AgendamentoDetalheSerializer,
    CriarAgendamentoSerializer,
)
from app.services import lista_do_dia
from app.services.agendamentos import (
    ErroCliente,
    cancelar_publico,
    detalhe_publico,
    eh_sobreposicao,
    marcar,
)
from app.services.mensagens import (
    msg_barbeiro_cancelado,
    msg_barbeiro_novo,
    msg_cancelamento,
    msg_confirmacao,
)
from app.services.trava_ip import ip_de
from app.services.whatsapp import enviar_a_equipe_da, enviar_ao_cliente, numero_existe
from tenant.models import TipoMensagem
from tenant.telefone import formatar, normalizar
from tenant.tipos import palavras

NAO_ENCONTRADO = {"erro": "Agendamento não encontrado."}


class AgendamentosView(ExigeTenant, APIView):
    """POST /api/agendamentos — o cliente marca sozinho, sem sessao nenhuma.

    Mesmo motor do painel (`marcar()`, em app/services/agendamentos.py) mais
    UMA checagem que so' este lado faz: o oraculo `numero_existe` da
    Evolution, ANTES de abrir a transacao — chamada de rede nao pode segurar
    conexao de banco esperando API externa.
    """

    def post(self, request):
        entrada = CriarAgendamentoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche nome e WhatsApp pra gente."}, status=422)
        d = entrada.validated_data

        whatsapp = normalizar(d["whatsapp"])
        if not whatsapp:
            return Response({"erro": "Confere o WhatsApp — parece faltar dígito."}, status=422)

        ip = ip_de(request)
        if numero_existe(request.barbearia, whatsapp, ip) == "nao_existe":
            return Response(
                {"erro": "Esse número não tem WhatsApp. Confere pra gente?"}, status=422
            )

        agora = datetime.now(timezone.utc)
        try:
            criado = marcar(
                barbearia_id=self.barbearia_id, barbeiro_id=d["barbeiroId"],
                servico_id=d["servicoId"], inicio=d["inicio"],
                nome=d["nome"], whatsapp=whatsapp, agora=agora,
            )
        except ErroCliente as e:
            return Response({"erro": e.mensagem}, status=e.status)
        except IntegrityError as e:
            if eh_sobreposicao(e):
                return Response(
                    {"erro": "Esse horário acabou de ser pego. Escolhe outro?"}, status=409
                )
            raise

        # Fire-and-forget, DEPOIS do commit: falha de WhatsApp nao desfaz nada.
        link = f"{request.headers.get('origin', '')}/agendamento/{criado['codigo']}"
        enviar_ao_cliente(
            request.barbearia,
            whatsapp,
            msg_confirmacao(
                cliente_nome=d["nome"], barbeiro_nome=criado["barbeiro_nome"],
                servico_nome=criado["servico_nome"], inicio=criado["inicio"],
                endereco=request.barbearia.endereco, link=link,
                barbearia_nome=request.barbearia.nome,
                contato=request.barbearia.whatsapp_contato,
            ),
            tipo=TipoMensagem.CONFIRMACAO,
            cliente_nome=d["nome"],
        )
        # E o barbeiro, so' o que e' de HOJE: depois que a lista das 06:30
        # saiu, ele recebe a lista inteira refeita, com o horario novo
        # marcado. Outro dia nao manda nada — ele ve no painel e na lista das
        # 06:30 daquele dia. Ate 07/10/2026 todo horario mandava "Novo
        # horário", e com a casa cheia o WhatsApp dele virava fila de aviso.
        # O aviso curto ficou so' para a fila fora do ar.
        mudanca = lista_do_dia.avisar_mudanca(
            self.barbearia_id, criado["barbeiro_id"], agora,
            novos=[(criado["id"], criado["inicio"])],
        )
        if mudanca == lista_do_dia.FILA_FORA:
            enviar_a_equipe_da(
                self.barbearia_id,
                criado["barbeiro_whatsapp"],
                msg_barbeiro_novo(
                    cliente_nome=d["nome"], servico_nome=criado["servico_nome"],
                    inicio=criado["inicio"], agora=datetime.now(timezone.utc),
                ),
            )
        return Response({"codigo": criado["codigo"]}, status=201)


class AgendamentoDetalheView(ExigeTenant, APIView):
    """GET /api/agendamentos/<codigo> — o RLS garante que um codigo de OUTRA
    barbearia nao e' encontrado aqui."""

    def get(self, request, codigo):
        agora = datetime.now(timezone.utc)
        resultado = detalhe_publico(self.barbearia_id, codigo, agora)
        if resultado is None:
            return Response(NAO_ENCONTRADO, status=404)

        resultado["endereco"] = request.barbearia.endereco
        resultado["whatsapp_barbearia"] = formatar(request.barbearia.whatsapp_contato)
        return Response(AgendamentoDetalheSerializer(resultado).data)


class AgendamentoCancelarPublicoView(ExigeTenant, APIView):
    """POST /api/agendamentos/<codigo>/cancelar — pelo CODIGO, sem sessao."""

    def post(self, request, codigo):
        agora = datetime.now(timezone.utc)
        resultado = cancelar_publico(self.barbearia_id, codigo, agora)

        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "fora_do_prazo":
            contato = formatar(request.barbearia.whatsapp_contato)
            o_lugar = palavras(request.barbearia.tipo)["o_lugar"]
            return Response(
                {"erro": f"Passou do prazo de 1h. Chama {o_lugar} no zap: {contato}"},
                status=422,
            )
        if resultado["tipo"] == "ok":
            enviar_ao_cliente(
                request.barbearia,
                resultado["cliente_whatsapp"],
                msg_cancelamento(
                    barbeiro_nome=resultado["barbeiro_nome"], inicio=resultado["inicio"],
                    barbearia_nome=request.barbearia.nome,
                ),
                tipo=TipoMensagem.CANCELAMENTO,
                cliente_nome=resultado["cliente_nome"],
            )
            # Mesma regra de marcar: hoje, depois das 06:30, a lista refeita
            # sem o horario que caiu; outro dia, nada. So' no `tipo == "ok"` —
            # o `ja_cancelado` cai fora deste bloco de proposito, senao dois
            # toques no botao refariam a lista duas vezes.
            mudanca = lista_do_dia.avisar_mudanca(
                self.barbearia_id, resultado["barbeiro_id"], agora,
                cancelados=[(resultado["id"], resultado["inicio"])],
            )
            if mudanca == lista_do_dia.FILA_FORA:
                enviar_a_equipe_da(
                    self.barbearia_id,
                    resultado["barbeiro_whatsapp"],
                    msg_barbeiro_cancelado(
                        cliente_nome=resultado["cliente_nome"],
                        servico_nome=resultado["servico_nome"],
                        inicio=resultado["inicio"], agora=datetime.now(timezone.utc),
                    ),
                )
        # "ja_cancelado" cai aqui tambem, de proposito: quem apertou o botao
        # duas vezes queria o mesmo desfecho, e ele ja vale — 200 idempotente.
        return Response({"ok": True})
