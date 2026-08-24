from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.services.barbearia import ler


class BarbeariaView(ExigeTenant, APIView):
    """GET /api/barbearia — a vitrine do tenant, sem sessao.

    Irma de `BarbeariaPainelView`, e nao a mesma view com o mixin trocado: o
    painel LE E ESCREVE (PATCH do dono) e responde a equipe logada; esta so'
    le e responde a qualquer um. Juntar as duas faria uma rota publica passar
    a carregar um metodo de escrita, e o proximo a mexer teria de conferir o
    mixin para saber quem alcanca o que.

    O envelope repete o do `barbeariaAtual()` do Next ao pe da letra — as tres
    paginas ja leem `b.nome`, `b.endereco`, `b.horarioResumo` e
    `b.whatsappContato`. `id` NAO sai: quem o usava era o `comBarbearia(b.id,
    ...)` do RLS, que morre com o Prisma. Publicar id de tenant sem consumidor
    seria superficie a toa.
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
