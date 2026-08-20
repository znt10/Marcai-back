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
    """O corpo do login. Aceita `login` OU `whatsapp`, e os dois vao para o
    mesmo lugar.

    `whatsapp` era o nome certo enquanto o barbeiro era a unica coisa que
    entrava e o numero era a unica forma de entrar. Desde a fatia 3 o dono
    entra por EMAIL, entao o nome do campo passou a mentir sobre o conteudo.

    O campo velho continua aceito de proposito: a tela que ainda manda
    `whatsapp` e a do front, e ela so' e' mexida na fatia 4. Recusa-lo agora
    quebraria o login inteiro entre uma fatia e outra, para ganhar um nome
    melhor uma semana antes.

    Sem `min_length` na senha aqui, e isso e deliberado: validar o tamanho no
    login diria a quem chuta que a senha daquela conta e curta ou longa. O
    tamanho minimo e regra de CADASTRO, e por isso vive no convite.
    """

    login = serializers.CharField(required=False, allow_blank=True)
    whatsapp = serializers.CharField(required=False, allow_blank=True)
    senha = serializers.CharField()

    def validate(self, dados):
        valor = dados.get("login") or dados.get("whatsapp")
        if not valor:
            # Recusa de FORMA, e a view a traduz no mesmo 401 generico dos
            # outros desfechos — corpo sem identificador nao pode ser
            # distinguivel de senha errada.
            raise serializers.ValidationError("informe login ou whatsapp")
        dados["login"] = valor
        return dados


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
