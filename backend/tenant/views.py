from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Barbeiro
from .rls import com_barbearia


@api_view(["GET"])
def saude(request):
    """O canario da fatia 0. Prova tres coisas de uma vez:

    1. o Host virou tenant  -> `slug` e `barbearia`
    2. o RLS escopou        -> `barbeiros`, que muda entre as barbearias
    3. o cookie atravessa   -> `recebeu_cookie`, falso na primeira chamada e
       verdadeiro na segunda

    O cookie e descartavel porque NAO HA LOGIN nesta fatia — a autenticacao e
    a fatia 3. O que esta sendo verificado aqui e o caminho, nao a sessao: se
    um cookie emitido na 8000 volta a partir da 3000, o login de verdade vai
    andar sobre trilho ja testado.
    """
    if request.eh_admin:
        corpo = {"ok": True, "admin": True, "barbearia": None, "slug": None,
                 "barbeiros": None}
    else:
        with com_barbearia(request.barbearia.id):
            quantos = Barbeiro.objects.count()
        corpo = {
            "ok": True,
            "admin": False,
            "barbearia": request.barbearia.nome,
            "slug": request.barbearia.slug,
            "barbeiros": quantos,
        }

    corpo["recebeu_cookie"] = "saude" in request.COOKIES

    resposta = Response(corpo)
    # httponly como toda sessao deste produto. Sem `domain`: host-only e o que
    # faz ele atravessar 8000 -> 3000, ja que cookie ignora porta.
    resposta.set_cookie("saude", "1", httponly=True, samesite="Lax")
    return resposta
