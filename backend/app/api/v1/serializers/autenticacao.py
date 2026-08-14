from rest_framework import serializers

from tenant.config import SENHA_MINIMA

# As mensagens deste modulo tem ACENTO de proposito, ao contrario do resto do
# back. Elas nao sao log: sao o texto que aparece na tela do barbeiro, e o
# front as mostra verbatim (`corpo.erro` em client.ts). Escrever "invalidos"
# aqui trocaria a mensagem cuidada por uma com erro de portugues, visivel para
# o cliente final.

# UMA resposta para celular inexistente, senha errada e barbeiro sem senha —
# ver o comentario de `autenticar` em app/services/autenticacao.py. Este texto
# e copia exata do INVALIDO do route.ts.
INVALIDO = {"erro": "Celular ou senha inválidos."}

TRAVADO = {"erro": "Muitas tentativas. Tenta de novo daqui a pouco."}


class LoginSerializer(serializers.Serializer):
    """Espelha o `z.object({ whatsapp: z.string(), senha: z.string() })`.

    Sem `min_length` na senha aqui, e isso e deliberado: validar o tamanho no
    login diria a quem chuta que a senha daquela conta e curta ou longa. O
    tamanho minimo e regra de CADASTRO, e por isso vive no convite.
    """

    whatsapp = serializers.CharField()
    senha = serializers.CharField()


class ConviteSerializer(serializers.Serializer):
    senha = serializers.CharField(min_length=SENHA_MINIMA)

    # 422, e nao o 400 padrao do DRF: o route.ts responde 422 e a tela do
    # convite ja distingue os dois. Mudar o codigo aqui faria a mensagem
    # aparecer no lugar errado da tela.
    MENSAGEM = {"erro": f"A senha precisa de ao menos {SENHA_MINIMA} caracteres."}


class EuSerializer(serializers.Serializer):
    """Os tres campos que o painel le, e so eles. Lista branca pelo mesmo
    motivo do BarbeiroPublicoSerializer: `Barbeiro` carrega senhaHash,
    tokenVersion e conviteTokenHash, e um ModelSerializer publicaria cada
    coluna nova por padrao.
    """

    id = serializers.CharField()
    nome = serializers.CharField()
    papel = serializers.CharField()
