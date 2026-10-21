"""O Pix de cada barbeiro: ler, validar e gravar. Sempre o barbeiro da sessao,
nunca um id vindo de fora — nem o dono mexe na chave de outro."""

import uuid

from django.db.models import Q

from app.services.mensalidade import pix
from tenant.models import Barbeiro, BarbeiroServico
from tenant.rls import com_barbearia

CHAVE_MAX = 77  # limite do campo 01 do merchant account info no BR Code
TITULAR_MAX = 60


TIPOS = ("CPF", "CNPJ", "CELULAR", "EMAIL", "ALEATORIA")


def _digito_cpf_cnpj(digitos: str, pesos: list[int]) -> int:
    resto = sum(int(d) * p for d, p in zip(digitos, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def _cpf_valido(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    return (
        _digito_cpf_cnpj(d[:9], list(range(10, 1, -1))) == int(d[9])
        and _digito_cpf_cnpj(d[:10], list(range(11, 1, -1))) == int(d[10])
    )


def _cnpj_valido(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return (
        _digito_cpf_cnpj(d[:12], p1) == int(d[12])
        and _digito_cpf_cnpj(d[:13], [6] + p1) == int(d[13])
    )


def forma_padrao(tipo, texto) -> tuple[str | None, str | None]:
    """(chave na forma do DICT, None) ou (None, frase de erro para a tela).

    O barbeiro diz o TIPO, como nos apps de banco: 11 digitos servem de CPF e
    de celular, e so' ele sabe qual e'. Gravar a forma padrao (e nao o que foi
    digitado) e' o que faz o copia e cola pagar e a mesma chave, escrita de
    dois jeitos, contar como uma so' no indice de centavos."""
    texto = (texto or "").strip()
    if tipo not in TIPOS:
        return None, "Escolha o tipo da chave Pix."
    if tipo in ("CPF", "CNPJ"):
        d = "".join(c for c in texto if c.isascii() and c.isdigit())
        if tipo == "CPF" and _cpf_valido(d):
            return d, None
        if tipo == "CNPJ" and _cnpj_valido(d):
            return d, None
        return None, f"Esse {tipo} não é válido."
    if tipo == "CELULAR":
        d = "".join(c for c in texto if c.isascii() and c.isdigit())
        if len(d) in (12, 13) and d.startswith("55"):
            d = d[2:]
        if len(d) in (10, 11) and d[0] in "123456789" and d[1] != "0" and (
            len(d) == 10 or d[2] == "9"
        ):
            return "+55" + d, None
        return None, "Esse celular não é válido. Use DDD e número."
    if tipo == "EMAIL":
        email = texto.lower()
        antes, _, depois = email.partition("@")
        if (
            antes and depois and "@" not in depois and len(email) <= CHAVE_MAX
            and not any(c.isspace() for c in email)
        ):
            return email, None
        return None, "Esse e-mail não é válido."
    try:
        u = uuid.UUID(texto)
    except ValueError:
        return None, "Essa chave aleatória não é válida."
    return str(u), None


def validar_titular(titular) -> str | None:
    # Depois de tirar acento e simbolo, como o copia e cola faz: um titular
    # so' de emoji deixaria o campo 59 vazio e o BR Code invalido.
    if not any(c.isalnum() for c in pix._sem_acento(titular)):
        return "Informe o nome do titular da chave."
    if len(titular) > TITULAR_MAX:
        return f"O nome do titular tem no máximo {TITULAR_MAX} caracteres."
    return None


def _sem_preco(barbeiro_id) -> list[str]:
    # Zero conta como sem preco (o CHECK do banco ja' o proibe; aqui e' cinto):
    # com o centavo a mais viraria cobranca de R$ 0,01.
    vinculos = BarbeiroServico.objects.filter(
        Q(preco_centavos__isnull=True) | Q(preco_centavos__lte=0),
        barbeiro_id=barbeiro_id, ativo=True, servico__ativo=True,
    ).select_related("servico").order_by("servico__ordem", "servico__nome")
    return [v.servico.nome for v in vinculos]


def _corpo(b: Barbeiro, sem_preco: list[str]) -> dict:
    return {
        "cobraNoAgendamento": b.cobra_no_agendamento,
        "pixTipo": b.pix_tipo,
        "pixChave": b.pix_chave,
        "pixTitular": b.pix_titular,
        "servicosSemPreco": sem_preco,
    }


def ver(barbearia_id, barbeiro_id) -> dict:
    with com_barbearia(barbearia_id):
        b = Barbeiro.objects.get(id=barbeiro_id)
        return _corpo(b, _sem_preco(barbeiro_id))


def mudar(barbearia_id, barbeiro_id, dados: dict) -> tuple[int, dict]:
    """(status, corpo). `dados` ja' vem com tipos conferidos pela view; so'
    as chaves presentes mudam. Ligado (ou continuando ligado) exige chave,
    titular e preco em todo servico ativo; desligar e' sempre livre e mantem
    chave e titular para o barbeiro nao redigitar."""
    with com_barbearia(barbearia_id):
        # FOR UPDATE: dois PUT juntos nao se atropelam entre a conferencia e
        # a gravacao.
        b = Barbeiro.objects.select_for_update().get(id=barbeiro_id)
        tipo = dados["pixTipo"].strip() if "pixTipo" in dados else b.pix_tipo
        chave = dados["pixChave"].strip() if "pixChave" in dados else b.pix_chave
        titular = dados["pixTitular"].strip() if "pixTitular" in dados else b.pix_titular
        liga = dados.get("cobraNoAgendamento", b.cobra_no_agendamento)

        # Chave nova (ou tipo novo) sempre passa pela forma padrao, ligado ou
        # nao: rascunho torto guardado so' estouraria na hora de ligar. A que
        # ja esta gravada ja' esta na forma padrao.
        if chave and ("pixChave" in dados or "pixTipo" in dados):
            chave, erro = forma_padrao(tipo, chave)
            if erro:
                return 400, {"erro": erro}
        elif not chave:
            chave = ""

        sem_preco = _sem_preco(barbeiro_id)
        if liga:
            erro = (
                (None if chave else "Informe a chave Pix.")
                or validar_titular(titular)
            )
            if erro:
                return 400, {"erro": erro}
            if sem_preco:
                return 400, {
                    "erro": "Cadastre o preço de todos os seus serviços antes de cobrar no agendamento.",
                    "servicosSemPreco": sem_preco,
                }

        b.cobra_no_agendamento, b.pix_tipo, b.pix_chave, b.pix_titular = (
            liga, tipo, chave, titular,
        )
        b.save(update_fields=["cobra_no_agendamento", "pix_tipo", "pix_chave", "pix_titular"])
        return 200, _corpo(b, sem_preco)
