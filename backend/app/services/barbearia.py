from tenant.models import Barbearia
from tenant.rls import com_barbearia


def ler(barbearia_id: str) -> dict:
    """Le do BANCO, e nao do cache de slug->Barbearia (que vive por
    `TTL_CACHE_TENANT_S`): servido dali, o dono salvava a frase e a tela
    continuava mostrando a antiga por ate um minuto — exatamente na hora em
    que ele quer ver que deu certo."""
    with com_barbearia(barbearia_id):
        return Barbearia.objects.filter(id=barbearia_id).values(
            "nome", "endereco", "horario_resumo", "whatsapp_contato"
        ).first()


def atualizar_horario_resumo(barbearia_id: str, horario_resumo: str) -> None:
    """`brutus_app` so tem GRANT UPDATE na coluna `horarioResumo` de
    `Barbearia` (migration `20260807120000_frase_do_horario`) — e' a UNICA
    coluna que o runtime escreve; o resto e' so o admin da plataforma."""
    with com_barbearia(barbearia_id):
        Barbearia.objects.filter(id=barbearia_id).update(horario_resumo=horario_resumo)
