"""Os centavos que distinguem um Pix de outro na mesma chave.

Sem gateway, o unico jeito de saber qual cobranca foi paga e o valor: cada
cobranca aberta numa chave leva de 1 a 99 centavos a mais que o preco.
"""


class SemCentavoLivre(Exception):
    """Os 99 centavos da faixa ja estao em cobrancas abertas na mesma chave."""


def escolher(base_centavos, ocupados):
    """O valor a cobrar: base + k, com k o menor de 1 a 99 que `ocupados`
    (valores em centavos das cobrancas abertas da chave) ainda nao usa.
    Nunca k = 0: o valor redondo e o de quem paga sem cobranca."""
    for k in range(1, 100):
        if base_centavos + k not in ocupados:
            return base_centavos + k
    raise SemCentavoLivre(base_centavos)


INDICE_DE_CENTAVOS = "cobranca_aberta_por_chave_e_valor"
TENTATIVAS_DE_CENTAVO = 3


def eh_disputa_de_centavo(exc: BaseException) -> bool:
    """So' a violacao do indice unico de centavos e' "outra cobranca pegou o
    mesmo centavo agora". Qualquer outro IntegrityError (a FK adiada do
    agendamento, o OneToOne) e' defeito de verdade e tem de subir com a causa
    certa, nao virar "chave sem centavo livre". O nome mora em
    `diag.constraint_name` dentro de `__cause__`, como em `eh_sobreposicao`."""
    atual: BaseException | None = exc
    for _ in range(5):
        if atual is None:
            return False
        diag = getattr(atual, "diag", None)
        if diag is not None and getattr(diag, "constraint_name", None) == INDICE_DE_CENTAVOS:
            return True
        atual = getattr(atual, "__cause__", None)
    return INDICE_DE_CENTAVOS in str(exc)


def ocupados(chave, *, using="admin"):
    """Os valores em uso por cobrancas abertas da chave, de QUALQUER barbearia
    e de qualquer motivo: o vigia so' distingue um Pix do outro pelo valor."""
    from tenant.models import Cobranca, StatusCobranca

    return set(
        Cobranca.objects.using(using)
        .filter(chave_pix=chave, status=StatusCobranca.ABERTA)
        .values_list("valor_centavos", flat=True)
    )


def criar_com_centavo_livre(chave, base_centavos, criar, *, ocupados_de=None, using="admin"):
    """Escolhe o menor centavo livre da chave e chama `criar(valor)` num
    savepoint. O indice unico parcial e' a palavra final: se outra cobranca
    pegou o mesmo centavo entre a leitura e a gravacao, o savepoint desfaz (sem
    matar a transacao de fora) e a busca roda de novo, algumas vezes.

    `ocupados_de(chave)` troca a leitura dos valores em uso (os testes
    simulam a corrida por ali).

    Levanta `SemCentavoLivre` se os 99 centavos acabaram ou se perdeu todas as
    corridas; outro erro de banco sobe como veio."""
    from django.db import IntegrityError, transaction

    for _ in range(TENTATIVAS_DE_CENTAVO):
        em_uso = ocupados_de(chave) if ocupados_de else ocupados(chave, using=using)
        valor = escolher(base_centavos, em_uso)
        try:
            with transaction.atomic(using=using):
                return criar(valor)
        except IntegrityError as e:
            if not eh_disputa_de_centavo(e):
                raise
    raise SemCentavoLivre(base_centavos)
