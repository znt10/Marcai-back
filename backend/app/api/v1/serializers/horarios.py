from rest_framework import serializers

from tenant.datas import como_utc


class InstanteISO(serializers.Field):
    """O MESMO texto que o `Date.toISOString()` do JavaScript produz:
    `2026-08-13T12:00:00.000Z`.

    Campo proprio porque o `DateTimeField` do DRF nao chega la por nenhum
    caminho: o padrao dele imprime `2026-08-13T12:00:00Z`, SEM os milissegundos,
    e um `format` com `%f` imprime SEIS digitos (microssegundos), nao tres.

    Isso importa mesmo o front usando `new Date(...)` nos dois casos, porque a
    travessia e verificada comparando as duas respostas byte a byte. Uma
    diferenca de formatacao aqui gastaria a comparacao inteira — e pior, ela
    apareceria como "as respostas divergem", escondendo qualquer divergencia
    de verdade no meio.

    `como_utc` antes de formatar: a coluna e `timestamp WITHOUT time zone`, e
    imprimir um valor sem fuso com um `Z` no fim seria uma mentira de 3 horas.
    """

    def to_representation(self, value):
        quando = como_utc(value)
        return f"{quando.strftime('%Y-%m-%dT%H:%M:%S')}.{quando.microsecond // 1000:03d}Z"


class SlotSerializer(serializers.Serializer):
    """Um horario LIVRE. Nada aqui identifica cliente nem revela ocupacao —
    o que sai e o instante, quanto dura e de quem e a vaga (9.1).
    """

    hora = serializers.CharField()
    inicio = InstanteISO()
    fim = InstanteISO()
    barbeiroId = serializers.CharField()
    barbeiroNome = serializers.CharField()
    duracaoMin = serializers.IntegerField()


class DiaSerializer(serializers.Serializer):
    data = serializers.CharField()
    rotulo = serializers.CharField()
    slots = SlotSerializer(many=True)
