from datetime import datetime, timezone

from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.agendamentos import (
    AgendamentoDetalheSerializer,
    CriarAgendamentoSerializer,
)
from app.services.agendamentos import (
    ErroCliente,
    cancelar_publico,
    detalhe_publico,
    eh_sobreposicao,
    marcar,
)
from app.services.mensagens import msg_cancelamento, msg_confirmacao
from app.services.trava_ip import ip_de
from app.services.whatsapp import enviar_texto, numero_existe
from tenant.telefone import formatar, normalizar

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
        if numero_existe(whatsapp, ip) == "nao_existe":
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
        enviar_texto(
            whatsapp,
            msg_confirmacao(
                cliente_nome=d["nome"], barbeiro_nome=criado["barbeiro_nome"],
                servico_nome=criado["servico_nome"], inicio=criado["inicio"],
                endereco=request.barbearia.endereco, link=link,
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
            return Response(
                {"erro": f"Passou do prazo de 1h. Chama a barbearia no zap: {contato}"},
                status=422,
            )
        if resultado["tipo"] == "ok":
            enviar_texto(
                resultado["cliente_whatsapp"],
                msg_cancelamento(
                    barbeiro_nome=resultado["barbeiro_nome"], inicio=resultado["inicio"],
                ),
            )
        # "ja_cancelado" cai aqui tambem, de proposito: quem apertou o botao
        # duas vezes queria o mesmo desfecho, e ele ja vale — 200 idempotente.
        return Response({"ok": True})
