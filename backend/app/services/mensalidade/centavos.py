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
