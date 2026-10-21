"""O Pix de cada barbeiro: ler, validar e gravar. Sempre o barbeiro da sessao,
nunca um id vindo de fora — nem o dono mexe na chave de outro."""

from app.services.mensalidade import pix
from tenant.models import Barbeiro, BarbeiroServico
from tenant.rls import com_barbearia

CHAVE_MAX = 77  # limite do campo 01 do merchant account info no BR Code
TITULAR_MAX = 60


def validar_chave(chave) -> str | None:
    """Mensagem de erro, ou None se serve. A chave e' medida normalizada (e' a
    forma que vai para o copia e cola), mas guardada como foi digitada."""
    normalizada = pix.normalizar_chave(chave)
    if not normalizada:
        return "Informe a chave Pix."
    if len(normalizada) > CHAVE_MAX:
        return f"A chave Pix tem no máximo {CHAVE_MAX} caracteres."
    return None


def validar_titular(titular) -> str | None:
    if not titular:
        return "Informe o nome do titular da chave."
    if len(titular) > TITULAR_MAX:
        return f"O nome do titular tem no máximo {TITULAR_MAX} caracteres."
    return None


def _sem_preco(barbearia_id, barbeiro_id) -> list[str]:
    vinculos = BarbeiroServico.objects.filter(
        barbeiro_id=barbeiro_id, ativo=True, servico__ativo=True, preco_centavos__isnull=True,
    ).select_related("servico").order_by("servico__ordem", "servico__nome")
    return [v.servico.nome for v in vinculos]


def _corpo(b: Barbeiro, sem_preco: list[str]) -> dict:
    return {
        "cobraNoAgendamento": b.cobra_no_agendamento,
        "pixChave": b.pix_chave,
        "pixTitular": b.pix_titular,
        "servicosSemPreco": sem_preco,
    }


def ver(barbearia_id, barbeiro_id) -> dict:
    with com_barbearia(barbearia_id):
        b = Barbeiro.objects.get(id=barbeiro_id)
        return _corpo(b, _sem_preco(barbearia_id, barbeiro_id))


def mudar(barbearia_id, barbeiro_id, dados: dict) -> tuple[int, dict]:
    """(status, corpo). `dados` ja' vem com tipos conferidos pela view; so'
    as chaves presentes mudam. Ligado (ou continuando ligado) exige chave,
    titular e preco em todo servico ativo; desligar e' sempre livre e mantem
    chave e titular para o barbeiro nao redigitar."""
    with com_barbearia(barbearia_id):
        # FOR UPDATE: dois PUT juntos nao se atropelam entre a conferencia e
        # a gravacao.
        b = Barbeiro.objects.select_for_update().get(id=barbeiro_id)
        chave = dados["pixChave"].strip() if "pixChave" in dados else b.pix_chave
        titular = dados["pixTitular"].strip() if "pixTitular" in dados else b.pix_titular
        liga = dados.get("cobraNoAgendamento", b.cobra_no_agendamento)

        sem_preco = _sem_preco(barbearia_id, barbeiro_id)
        if liga:
            erro = validar_chave(chave) or validar_titular(titular)
            if erro:
                return 400, {"erro": erro}
            if sem_preco:
                return 400, {
                    "erro": "Cadastre o preço de todos os seus serviços antes de cobrar no agendamento.",
                    "servicosSemPreco": sem_preco,
                }

        b.cobra_no_agendamento, b.pix_chave, b.pix_titular = liga, chave, titular
        b.save(update_fields=["cobra_no_agendamento", "pix_chave", "pix_titular"])
        return 200, _corpo(b, sem_preco)
