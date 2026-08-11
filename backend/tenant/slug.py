from .config import SLUG_REGEX, SUBDOMINIOS_RESERVADOS


def extrair_slug(host: str, dominio_base: str) -> str | None:
    """Traduz o Host da requisicao no slug da barbearia.

    Porte de front/src/lib/slug.ts, caso a caso. Vive sem nenhuma dependencia
    de banco ou de Django porque o middleware e os testes a chamam antes de
    existir tenant — e porque funcao pura e o que menos pode divergir entre os
    dois lados durante a travessia.
    """
    sem_porta = host.split(":")[0].lower()
    if sem_porta == dominio_base:
        return None
    if not sem_porta.endswith(f".{dominio_base}"):
        return None

    slug = sem_porta[: -(len(dominio_base) + 1)]
    if "." in slug:  # subdominio de subdominio nao e tenant
        return None
    if slug in SUBDOMINIOS_RESERVADOS:
        return None
    if not SLUG_REGEX.fullmatch(slug):
        return None
    return slug


def eh_host_admin(host: str, dominio_base: str) -> bool:
    """`extrair_slug` devolve None para DOIS casos diferentes — o dominio nu e
    um subdominio reservado — e quem roteia precisa distingui-los: um serve a
    pagina institucional, o outro serve o painel de admin.
    """
    return host.split(":")[0].lower() == f"admin.{dominio_base}"
