from rest_framework import serializers

from tenant.models import PlanoBarbearia


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

    def validate(self, dados):
        if not dados:
            raise serializers.ValidationError("Informe ativo ou plano.")
        return dados
