import json
import math

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.serializers.admin_autenticacao import INVALIDO
from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir
from app.services.admin_senha import conferir_senha
from app.services.trava_ip import espera_de, falhas_de, ip_de, limpar_falhas, registrar_falha
from tenant.config import ADMIN_SESSAO_HORAS, ADMIN_TRAVA_TENTATIVAS


class AdminLoginView(APIView):
    """POST /api/admin/auth/login

    Sem mixin nenhum: o host ja e' o do admin (a `BarreiraAdminMiddleware`
    garante isso por posicao — de outro host esta rota nem e' alcancada), e
    ainda nao ha sessao pra exigir, e' o login que a cria.
    """

    def post(self, request):
        ip = ip_de(request)

        # A espera e' conferida ANTES de tocar a senha: o argon2 e' caro de
        # proposito, e deixar o atacante gasta-lo a vontade e' o que a trava
        # evita.
        espera = espera_de(ip)
        if espera > 0:
            minutos = math.ceil(espera / 60_000)
            bloqueado = falhas_de(ip) >= ADMIN_TRAVA_TENTATIVAS
            corpo = {
                "erro": (
                    f"Muitas tentativas. Bloqueado por {minutos} min."
                    if bloqueado
                    else "Muitas tentativas. Espera um pouco."
                )
            }
            resposta = Response(corpo, status=429)
            resposta["retry-after"] = str(math.ceil(espera / 1000))
            return resposta

        try:
            corpo = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            corpo = {}
        usuario = str(corpo.get("usuario") or "")
        senha = str(corpo.get("senha") or "")

        if not conferir_senha(usuario, senha):
            registrar_falha(ip)
            return Response(INVALIDO, status=401)

        limpar_falhas(ip)
        resposta = Response({"ok": True})
        resposta.set_cookie(
            COOKIE_SESSAO_ADMIN,
            emitir(),
            max_age=ADMIN_SESSAO_HORAS * 3600,
            path="/",
            httponly=True,
            samesite="Lax",
            secure=not settings.DEBUG,
        )
        return resposta


class AdminLogoutView(APIView):
    """POST /api/admin/auth/logout — sempre 200, mesma razao do logout do
    barbeiro: sair tem que funcionar mesmo com cookie corrompido."""

    def post(self, request):
        resposta = Response({"ok": True})
        resposta.delete_cookie(COOKIE_SESSAO_ADMIN, path="/")
        return resposta
