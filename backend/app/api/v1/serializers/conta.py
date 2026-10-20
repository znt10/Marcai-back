from rest_framework import serializers

from tenant.config import CONTA_SENHA_MINIMA

# Como em serializers/autenticacao.py, estes textos tem ACENTO de proposito: o
# front os mostra verbatim (`corpo.erro` em client.ts).

# Os desfechos de acesso. Cada um e' UMA frase para varios motivos, de
# proposito: quem erra o numero, a senha ou o codigo recebe a mesma resposta.
ERRO_ENTRAR = {"erro": "WhatsApp ou senha errados."}
ERRO_CODIGO = {"erro": "Código errado ou vencido."}
ERRO_LINK = {"erro": "Link inválido ou vencido."}
JA_TEM_CONTA = {"erro": "Esse WhatsApp já tem conta. Entra com sua senha."}
MUITOS_CODIGOS = {"erro": "Muitos códigos pedidos. Tenta de novo mais tarde."}
CENTRAL_FORA = {"erro": "Não conseguimos mandar o código agora. Tenta de novo mais tarde."}
TRAVADO = {"erro": "Muitas tentativas. Tenta de novo daqui a pouco."}
NUMERO_INVALIDO = {"erro": "Esse número de WhatsApp não parece certo."}
SEM_WHATSAPP = {"erro": "Esse número não tem WhatsApp. Confere se digitou certo."}

# Tetos de tamanho: a senha passa pelo argon2 e o nome vai para o banco, entao
# um corpo de megabytes nao pode chegar la.
_NOME_MAX = 80
_SENHA_MAX = 128


class _Serializer(serializers.Serializer):
    # 422 e nao o 400 padrao do DRF, como o convite: a tela distingue os dois.
    MENSAGENS: dict[str, str] = {}

    def recusa(self) -> dict:
        """A primeira mensagem de campo, na ordem em que o corpo e' lido."""
        for campo in self.fields:
            if campo in self.errors:
                return {"erro": self.MENSAGENS[campo]}
        return {"erro": "Confere os dados e tenta de novo."}


class CriarSerializer(_Serializer):
    nome = serializers.CharField(min_length=2, max_length=_NOME_MAX)
    whatsapp = serializers.CharField(max_length=40)
    # Sem `trim_whitespace`: espaco na ponta de uma senha e' parte dela, e
    # aparar aqui faria o login (que nao apara) nunca mais bater.
    senha = serializers.CharField(
        min_length=CONTA_SENHA_MINIMA, max_length=_SENHA_MAX, trim_whitespace=False,
    )

    MENSAGENS = {
        "nome": "Escreve seu nome.",
        "whatsapp": NUMERO_INVALIDO["erro"],
        "senha": f"A senha precisa de ao menos {CONTA_SENHA_MINIMA} caracteres.",
    }


class WhatsappSerializer(_Serializer):
    whatsapp = serializers.CharField(max_length=40)

    MENSAGENS = {"whatsapp": NUMERO_INVALIDO["erro"]}


class ConfirmarSerializer(serializers.Serializer):
    """So' garante que os dois campos sao TEXTO: `conferir_codigo(None)`
    quebraria no `.strip()`. Qualquer defeito vira o mesmo 400 do codigo
    errado, sem dizer qual."""

    whatsapp = serializers.CharField(max_length=40)
    codigo = serializers.CharField(max_length=32)


class EntrarSerializer(serializers.Serializer):
    """Sem `min_length` na senha, pelo motivo do `LoginSerializer`: o tamanho
    minimo e' regra de cadastro, e validar aqui diria a quem chuta que a senha
    daquela conta e' curta. O `max_length` e' so' o teto contra o argon2."""

    whatsapp = serializers.CharField(max_length=40)
    senha = serializers.CharField(max_length=_SENHA_MAX, trim_whitespace=False)


class NovaSenhaSerializer(_Serializer):
    senha = serializers.CharField(
        min_length=CONTA_SENHA_MINIMA, max_length=_SENHA_MAX, trim_whitespace=False,
    )

    MENSAGENS = {"senha": CriarSerializer.MENSAGENS["senha"]}
