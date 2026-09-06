from datetime import datetime, timezone

from django.db import IntegrityError
from django.http import HttpResponse
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
from app.services.calendario import ics_do_agendamento
from app.services.mensagens import (
    msg_barbeiro_cancelado,
    msg_barbeiro_novo,
    msg_cancelamento,
    msg_confirmacao,
)
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
        # E o barbeiro. Segundo envio, e nao um destinatario a mais no mesmo:
        # sao textos diferentes — o do cliente confirma e da o link de
        # cancelar; o do barbeiro so' avisa que entrou horario.
        enviar_texto(
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
            # A vaga abriu: quem ia cortar precisa saber sem abrir o painel.
            # So' no `tipo == "ok"` — o `ja_cancelado` cai fora deste bloco de
            # proposito, senao dois toques no botao mandariam dois avisos.
            enviar_texto(
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


class AgendamentoIcsView(ExigeTenant, APIView):
    """GET /api/agendamentos/<codigo>/ics — o evento para o calendario do celular.

    Rota propria, e nao um campo na resposta do detalhe, porque o que o iPhone
    precisa e' de uma URL que responda `Content-Type: text/calendar`. Era isso
    que faltava: a tela montava o mesmo arquivo num `Blob` com
    `a.download`, e o Safari do iOS ignora o `download` em URL `blob:` — o
    botao nao fazia nada, ou abria o texto cru na tela.

    Publica pelo CODIGO, como o detalhe e o cancelamento ao lado: quem tem o
    link tem o horario, e o RLS garante que um codigo de outra barbearia nao
    e' encontrado aqui.
    """

    def get(self, request, codigo):
        agora = datetime.now(timezone.utc)
        a = detalhe_publico(self.barbearia_id, codigo, agora)
        if a is None:
            return Response(NAO_ENCONTRADO, status=404)

        texto = ics_do_agendamento(
            codigo=a["codigo"], servico_nome=a["servico_nome"],
            barbeiro_nome=a["barbeiro_nome"], barbearia_nome=request.barbearia.nome,
            inicio=a["inicio"], fim=a["fim"], endereco=request.barbearia.endereco,
            status=a["status"], agora=agora,
        )
        resposta = HttpResponse(texto, content_type="text/calendar; charset=utf-8")
        # `attachment` com nome: e' o que faz o iOS abrir a folha do Calendario
        # em vez de renderizar o texto. O nome aparece na folha, entao ele diz
        # o que e' em vez de "download.ics".
        resposta["Content-Disposition"] = f'attachment; filename="marcai-{codigo}.ics"'
        return resposta
