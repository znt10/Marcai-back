from tenant.models import PAR_DA_PALETA, Barbearia
from tenant.rls import com_barbearia


def ler(barbearia_id: str) -> dict:
    """Le do BANCO, e nao do cache de slug->Barbearia (que vive por
    `TTL_CACHE_TENANT_S`): servido dali, o dono salvava a frase e a tela
    continuava mostrando a antiga por ate um minuto — exatamente na hora em
    que ele quer ver que deu certo."""
    with com_barbearia(barbearia_id):
        return Barbearia.objects.filter(id=barbearia_id).values(
            "nome", "endereco", "horario_resumo", "whatsapp_contato", "tipo", "paleta",
            "logo_url",
        ).first()


def atualizar_horario_resumo(barbearia_id: str, horario_resumo: str) -> None:
    """`brutus_app` so tem GRANT UPDATE na coluna `horarioResumo` de
    `Barbearia` (migration `20260807120000_frase_do_horario`) e na
    `hora_da_lista_min` (0009, ver `lista_do_dia.mudar_hora_da_lista`) — o
    resto e' so o admin da plataforma."""
    with com_barbearia(barbearia_id):
        Barbearia.objects.filter(id=barbearia_id).update(horario_resumo=horario_resumo)


def trocar_paleta(barbearia_id: str, paleta: str) -> bool:
    """O dono troca a tela do cliente entre o claro e o escuro da MESMA cor
    (`PAR_DA_PALETA`). Outra cor e' do admin: devolve False sem gravar.
    `brutus_app` tem GRANT UPDATE so' nesta coluna para isso (0025)."""
    with com_barbearia(barbearia_id):
        atual = Barbearia.objects.filter(id=barbearia_id).values_list("paleta", flat=True).first()
        if atual is None:
            return False
        if paleta != atual and PAR_DA_PALETA.get(atual) != paleta:
            return False
        Barbearia.objects.filter(id=barbearia_id).update(paleta=paleta)
    # A tela publica le a barbearia por um cache de slug com TTL curto;
    # limpar o deste processo faz o dono ver a troca na hora.
    from tenant.middleware import _limpar_cache_tenant

    _limpar_cache_tenant()
    return True
