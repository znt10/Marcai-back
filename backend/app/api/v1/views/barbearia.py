from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.services.barbearia import ler


class BarbeariaView(ExigeTenant, APIView):
    """GET /api/barbearia — os dados que a vitrine mostra, sem sessao nenhuma.

    Irma PUBLICA de `BarbeariaPainelView` (`/api/painel/barbearia`), que ja
    devolvia exatamente estes campos e reusa o mesmo `ler()`. A diferenca e' so'
    quem pode chamar: aquela e' `ExigeSessao`, e a home, a pagina de convite e a
    de agendamento sao anonimas por definicao — quem as abre ainda nem e'
    cliente.

    Nasce na fatia 4, e o motivo e' direto: enquanto o front tinha Prisma, as
    paginas liam a barbearia do banco elas mesmas (`barbeariaAtual()` em
    `lib/tenant.ts`). Tirando o Prisma de la, elas precisam de alguem a quem
    perguntar, e esse alguem passa a ser esta rota.

    Nenhum campo novo e exposto: os quatro ja apareciam em tela publica —
    `nome`, `endereco` e `horario_resumo` na home, e `whatsapp_contato` na
    pagina de agendamento confirmado (onde o cliente fala com a barbearia).
    Quem NAO sai daqui e o que so' o painel ve, e a lista continua a mesma
    porque a fonte e a mesma funcao.

    `ExigeTenant` sem `ExigeSessao`: o Host ja diz qual barbearia e', e o
    `TenantMiddleware` recusa host desconhecido antes de chegar aqui. Do host
    do admin isso da 404, nao 500 — e' o que o mixin existe para garantir.
    """

    def get(self, request):
        dados = ler(self.barbearia_id)
        return Response(
            {
                "nome": dados["nome"],
                "endereco": dados["endereco"],
                "horarioResumo": dados["horario_resumo"],
                "whatsappContato": dados["whatsapp_contato"],
            }
        )
