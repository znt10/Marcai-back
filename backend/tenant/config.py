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
