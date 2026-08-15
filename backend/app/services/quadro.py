"""Os calculos do quadro do dia — aritmetica de intervalo, separada do resto
porque erra em silencio e so aparece como um numero estranho na tela. Porte
de front/src/lib/quadro.ts."""


def minutos_cobertos(intervalos: list[tuple], janela: tuple) -> int:
    """Minutos cobertos por `intervalos` dentro da `janela`, sem contar duas
    vezes o que se sobrepoe — dois bloqueios encavalados nao podem descontar
    o mesmo tempo duas vezes do denominador."""
    j_inicio, j_fim = janela
    recortados = sorted(
        (max(i, j_inicio), min(f, j_fim))
        for i, f in intervalos
        if min(f, j_fim) > max(i, j_inicio)
    )

    total = 0.0
    fim_atual = None
    for inicio, fim in recortados:
        comeca = max(inicio, fim_atual) if fim_atual is not None else inicio
        if fim > comeca:
            total += (fim - comeca).total_seconds()
        fim_atual = fim if fim_atual is None else max(fim_atual, fim)
    return round(total / 60)


def ocupacao_pct(agendamentos: list[tuple], bloqueios: list[tuple], janela: tuple) -> int:
    """Quanto da jornada ja esta vendido, em porcentagem inteira.

    O tempo bloqueado sai do DENOMINADOR em vez de entrar como ocupacao: com
    o almoco contando como disponivel, um dia genuinamente lotado marcaria
    88% e o dono nunca veria 100%. Jornada inteira bloqueada devolve 100 pelo
    mesmo motivo — nao cabe mais ninguem."""
    jornada = minutos_cobertos([janela], janela)
    disponivel = jornada - minutos_cobertos(bloqueios, janela)
    if disponivel <= 0:
        return 100

    vendido = minutos_cobertos(agendamentos, janela)
    return min(100, round((vendido / disponivel) * 100))
