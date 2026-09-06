import base64
import re

from tenant.config import FOTO_MIMES, FOTO_TAMANHO_MAXIMO_BYTES
from tenant.models import Barbeiro
from tenant.rls import com_barbearia

# `data:image/webp;base64,<...>` — o unico formato aceito. A foto chega ja'
# recortada e reduzida pelo navegador e mora na propria coluna `foto_url`, que
# e' TEXT desde a primeira migracao: sem volume, sem rota de arquivo, e o dump
# do banco leva as fotos junto.
_DATA_URL = re.compile(r"^data:([a-z0-9.+/-]+);base64,([A-Za-z0-9+/=\s]+)$", re.I)


def foto_invalida(valor: str) -> str | None:
    """A regra do SERVIDOR. O navegador ja recorta e reduz antes de mandar, mas
    isso e' conveniencia para quem usa a tela — nao barreira: `curl` nao passa
    por navegador nenhum.
    """
    casou = _DATA_URL.match(valor.strip())
    if not casou:
        # Recusa `https://...` de proposito, e nao so' por seguranca: uma URL
        # de terceiro faria a PRIMEIRA tela do cliente depender de um dominio
        # que nao e' nosso, e quebrar quando ele saisse do ar.
        return "Manda a foto pelo botão da tela."

    mime, dados = casou.group(1).lower(), casou.group(2)
    if mime not in FOTO_MIMES:
        # SVG e' o caso que importa: e' imagem que carrega script, e ela iria
        # parar num `<img src>` servido pelo dominio da propria barbearia.
        return "Essa imagem não serve. Manda uma foto (JPG, PNG ou WebP)."

    try:
        bruto = base64.b64decode(dados, validate=True)
    except (ValueError, base64.binascii.Error):
        return "A foto chegou quebrada. Tenta de novo?"

    if len(bruto) > FOTO_TAMANHO_MAXIMO_BYTES:
        # A vitrine e' renderizada no SERVIDOR: a foto entra embutida no HTML
        # da primeira tela que o cliente abre. Sem teto, uma foto de camera
        # mata justamente essa tela.
        return "A foto ficou grande demais. Tenta outra?"
    return None


def definir_foto(barbearia_id: str, barbeiro_id: str, foto: str | None) -> bool:
    with com_barbearia(barbearia_id):
        return Barbeiro.objects.filter(id=barbeiro_id).update(foto_url=foto) == 1
