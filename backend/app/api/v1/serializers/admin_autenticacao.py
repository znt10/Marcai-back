# Mesma resposta pra usuario inexistente e senha errada — o formulario nao
# pode servir pra descobrir se o usuario digitado existe. Copia exata do
# texto do route.ts.
#
# Sem serializer de entrada aqui de proposito: o corpo e' lido a mao na view
# (json.loads com fallback pra dict vazio), porque o route.ts trata JSON
# malformado como usuario/senha em branco (`.catch(() => ({usuario:'',
# senha:''}))`) em vez de recusar o pedido com 400 — e isso PRECISA continuar
# contando como uma tentativa falha pra trava por IP.
INVALIDO = {"erro": "usuário ou senha inválidos"}
