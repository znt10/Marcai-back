"""O seletor de barbearia do admin do Django.

Fica fora de `api/v1/` de proposito: aquilo e' a superficie JSON versionada que
o front consome, e isto devolve HTML para uma pessoa. Misturar os dois faria a
proxima pessoa procurar esta rota no `router.py`, onde ela nao esta.

O HTML e' escrito na mao, sem template: e' uma lista de botoes usada por UMA
pessoa, e um arquivo de template para isso seria mais lugar para procurar do
que economia de codigo.
"""

import uuid

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.utils.html import escape
from django.views.decorators.http import require_http_methods

from tenant.middleware import AdminDjangoMiddleware
from tenant.models import Barbearia

# A conexao "admin" (`brutus_admin`) e' quem enxerga `tenant_barbearia`:
# `brutus_app` tem REVOKE de escrita ali, e a leitura passa pelos dois — mas
# usar a mesma conexao do painel custom mantem UM lugar so' que fala com a
# tabela de tenant.
_CONEXAO = "admin"


@require_http_methods(["GET", "POST"])
def escolher_barbearia(request):
    if request.method == "POST":
        pedido = request.POST.get("barbearia_id") or ""
        # Forma invalida (campo ausente vira "" pelo `or ""` acima, texto
        # solto, tentativa de SQL) e id bem formado mas inexistente merecem a
        # MESMA resposta: as duas alegam "existe alguma barbearia com este
        # id", e nenhuma e' verdade. Sem validar a FORMA antes do `filter`,
        # `Barbearia.id` (UUIDField) faz o Django levantar `ValidationError`
        # DENTRO do ORM, antes de qualquer SQL rodar — e a view devolveria 500
        # em vez do 400 que a mesma pergunta ja merece para um UUID
        # inexistente.
        try:
            id_normalizado = uuid.UUID(pedido)
        except ValueError:
            return HttpResponseBadRequest("barbearia inexistente")

        barbearia = Barbearia.objects.using(_CONEXAO).filter(id=id_normalizado).first()
        if barbearia is None:
            return HttpResponseBadRequest("barbearia inexistente")

        # Grava a forma CANONICA (a que voltou do banco), nunca o texto cru
        # do POST: a politica de RLS compara `barbearia_id::text` (ver
        # tenant/migrations/0002_rls.py) contra `current_setting(...)`, e o
        # `::text` do Postgres sempre devolve minusculo com hifens. Um UUID
        # escrito diferente mas equivalente (maiusculo, sem hifen,
        # `urn:uuid:...`) passa no `filter` — o Django normaliza antes de
        # consultar — mas nunca vai igualar o `::text`, e o admin cairia no
        # mesmo "toda lista vem vazia e nada explica por que" que esta
        # validacao inteira existe para evitar.
        request.session[AdminDjangoMiddleware.CHAVE_SESSAO] = str(barbearia.id)
        return HttpResponseRedirect("/admin/django/")

    atual = request.session.get(AdminDjangoMiddleware.CHAVE_SESSAO)
    linhas = []
    for b in Barbearia.objects.using(_CONEXAO).order_by("slug"):
        marca = " ← atual" if str(b.id) == str(atual) else ""
        # Uma barbearia inativa e' recusada pelo `TenantMiddleware` em
        # producao (`_buscar_por_slug` filtra `ativo=True`): escolhe-la aqui
        # daria um admin funcional sobre um tenant que, do lado do
        # subdominio, nao existe mais. Listar todas continua certo — e' a
        # ferramenta do dono da plataforma — mas sem o aviso ninguem notaria
        # o descompasso antes de mexer em dado.
        aviso = "" if b.ativo else " (inativa)"
        linhas.append(
            f'<li><button name="barbearia_id" value="{escape(str(b.id))}">'
            f"{escape(b.slug)}</button> {escape(b.nome)}{aviso}{marca}</li>"
        )
    # `get_token(request)` (e nao `django.middleware.csrf.rotate_token`, nem
    # ler um cookie que ainda nao existe): esta pagina e' servida pela MESMA
    # origem que recebe o POST dela, e e' exatamente esse o caso em que o
    # token CSRF (nao o `X-Brutus-Cliente` da API, que o `ClienteMiddleware`
    # isenta neste prefixo desde a Task 2) e' a protecao certa. Sem o campo
    # oculto abaixo o `CsrfViewMiddleware` global (Task 1) recusa o POST com
    # 403 assim que alguem clicar um botao de verdade no navegador — o client
    # de teste padrao nao pegaria isso, porque ele desliga essa checagem.
    token = get_token(request)
    return HttpResponse(
        "<h1>De qual barbearia?</h1>"
        "<p>O admin mostra uma barbearia por vez — é o isolamento do banco, "
        "não um filtro da tela.</p>"
        f'<form method="post"><input type="hidden" name="csrfmiddlewaretoken" '
        f'value="{escape(token)}">'
        f"<ul>{''.join(linhas)}</ul></form>",
        content_type="text/html; charset=utf-8",
    )
