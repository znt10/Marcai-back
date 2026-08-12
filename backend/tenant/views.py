from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def saude(request):
    return Response(
        {
            "ok": True,
            "barbearia": request.barbearia.nome if request.barbearia else None,
            "admin": request.eh_admin,
        }
    )
