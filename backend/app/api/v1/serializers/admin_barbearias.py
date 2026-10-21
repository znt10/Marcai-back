from rest_framework import serializers

from tenant.models import PlanoBarbearia


class TextoEstrito(serializers.CharField):
    """CharField do DRF aceita numero e vira string ("12"); aqui so' texto."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class AtualizarBarbeariaSerializer(serializers.Serializer):
    """Dois campos, os DOIS opcionais, e pelo menos um obrigatorio.

    Era um campo so (`ativo`) e `required=True` — o que fazia corpo vazio cair
    no 422, igual ao `typeof ativo !== 'boolean'` do route.ts. Com o plano
    entrando, `required=True` nos dois obrigaria o admin a mandar `ativo` toda
    vez que quisesse so' trocar de plano, e vice-versa: um PATCH que exige o
    recurso inteiro e um PUT com outro nome.

    O `validate` devolve o corpo vazio ao mesmo 422 de antes. O que se perde
    em relacao ao `required=True` e a mensagem por campo, que esta rota nunca
    usou: a view responde uma frase so'.

    `partial=True` do DRF resolveria isto sozinho, mas so' em ModelSerializer
    com instancia — aqui nao ha model por tras, e `required=False` mais este
    `validate` dizem a mesma coisa sem fingir que ha.
    """

    ativo = serializers.BooleanField(required=False)
    # `choices` e nao CharField livre: plano inventado morre na borda, e nao
    # numa comparacao perdida la dentro que simplesmente nao casa com nada.
    plano = serializers.ChoiceField(choices=PlanoBarbearia.choices, required=False)
    # Vazia limpa (volta a valer "BRASIL" no Pix). 40: o limite do campo de
    # cidade do BR Code e' 15, mas o texto livre cabe aqui e a hora de cortar
    # e' ao montar o codigo.
    cidade = TextoEstrito(required=False, allow_blank=True, max_length=40)

    def validate(self, dados):
        if not dados:
            raise serializers.ValidationError("Informe ativo, plano ou cidade.")
        return dados
