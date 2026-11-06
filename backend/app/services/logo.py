import base64

from app.services.foto import _DATA_URL
from tenant.config import LOGO_MIMES, LOGO_TAMANHO_MAXIMO_BYTES
from tenant.models import Barbearia
from tenant.rls import com_barbearia


def logo_invalida(valor: str) -> str | None:
    """A regra do SERVIDOR para a logo — irma de `foto_invalida`, com o teto
    e as frases da logo. O navegador ja reduz antes de mandar (`lib/logo.ts`),
    mas `curl` nao passa por navegador nenhum."""
    casou = _DATA_URL.match(valor.strip())
    if not casou:
        # `https://...` recusado pelo mesmo motivo da foto: a primeira tela do
        # cliente nao pode depender de dominio que nao e' nosso.
        return "Manda a logo pelo botão da tela."

    mime, dados = casou.group(1).lower(), casou.group(2)
    if mime not in LOGO_MIMES:
        # SVG: imagem que carrega script, servida pelo dominio da casa.
        return "Essa imagem não serve. Manda a logo em JPG, PNG ou WebP."

    try:
        bruto = base64.b64decode(dados, validate=True)
    except (ValueError, base64.binascii.Error):
        return "A logo chegou quebrada. Tenta de novo?"

    if len(bruto) > LOGO_TAMANHO_MAXIMO_BYTES:
        return "A logo ficou grande demais. Tenta outra?"
    return None


def definir_logo(barbearia_id: str, logo: str | None) -> None:
    with com_barbearia(barbearia_id):
        Barbearia.objects.filter(id=barbearia_id).update(logo_url=logo)
