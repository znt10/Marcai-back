import re

# Espelha o SUBDOMINIOS_RESERVADOS de front/src/lib/config.ts. Divergir daqui
# significa um subdominio que um lado trata como barbearia e o outro nao.
SUBDOMINIOS_RESERVADOS = frozenset(
    {"www", "api", "app", "admin", "painel", "static", "assets", "cdn", "mail"}
)

# Espelha o SLUG_REGEX. Note que a forma exige no minimo 3 caracteres: uma
# letra, de 1 a 30 do miolo, e uma letra final.
#
# `fullmatch` sem `$`, e nao `match` com `$`: em Python o `$` tambem casa antes
# de um \n final, entao "brutus\n" passaria por um regex ancorado com `$`.
SLUG_REGEX = re.compile(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]")

# 60_000 ms do lado Next. Aqui em segundos, porque e o que o time.monotonic()
# devolve.
TTL_CACHE_TENANT_S = 60.0


def regex_de_origem(dominio_base: str) -> str:
    """Regex de origem para o django-cors-headers.

    A biblioteca so aceita lista estatica ou lista de regex, e aqui a origem
    varia por barbearia — entao e regex. O `slug.py` nao pode ser chamado de
    dentro dela, e por isso a regra e reconstruida aqui.

    O que NAO se pode fazer e reescrever a lista de reservados a mao: ela sai
    de SUBDOMINIOS_RESERVADOS, para que um nome novo la feche a porta aqui
    sozinho. Duas listas separadas param de acompanhar uma a outra em silencio.

    `admin` sai da exclusao: ele e reservado como SLUG (nao e barbearia), mas e
    uma origem legitima — o painel da plataforma chama a API a partir dele.
    """
    proibidos = "|".join(sorted(SUBDOMINIOS_RESERVADOS - {"admin"}))
    base = re.escape(dominio_base)
    # (?!…) recusa os reservados; [a-z0-9-]+ sem ponto recusa subdominio de
    # subdominio; a ancora de fim recusa sufixo forjado (…localhost.malicioso.com).
    #
    # `\Z`, e nao `$`: em Python o `$` tambem casa antes de um \n final (mesma
    # pegadinha do comentario do SLUG_REGEX acima), e quem chama este regex e
    # o django-cors-headers com `re.match` — nunca `re.fullmatch`. O truque do
    # SLUG_REGEX (fullmatch sem ancora) nao serve aqui porque quem decide o
    # metodo de match e a biblioteca, nao este modulo; a unica defesa
    # disponivel e trocar a ancora por uma que nao cede ao \n.
    return rf"^https?://(?!(?:{proibidos})\.)[a-z0-9-]+\.{base}(:\d+)?\Z"
