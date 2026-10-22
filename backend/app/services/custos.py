"""Os custos que o dono lanca no resumo. So' registro: o resumo mostra a
lista e o total do periodo, e nao tira nada do faturamento."""

from tenant.datas import formatar_instante_iso, local_para_utc, somar_dias
from tenant.models import Custo
from tenant.rls import com_barbearia


def listar_custos(barbearia_id: str, de: str, ate: str) -> dict:
    """Os custos lancados entre `de` e `ate` (dias locais, inclusive), do
    mais novo para o mais velho — o mesmo periodo que o resumo ja' le."""
    abre = local_para_utc(de, 0)
    fecha = local_para_utc(somar_dias(ate, 1), 0)
    with com_barbearia(barbearia_id):
        linhas = list(
            Custo.objects.filter(criado_em__gte=abre, criado_em__lt=fecha)
            .order_by("-criado_em")
            .values("id", "nome", "valor_centavos", "criado_em")
        )
    return {
        "custos": [
            {
                "id": str(c["id"]),
                "nome": c["nome"],
                "valorCentavos": c["valor_centavos"],
                "criadoEm": formatar_instante_iso(c["criado_em"]),
            }
            for c in linhas
        ],
        "totalCentavos": sum(c["valor_centavos"] for c in linhas),
    }


def lancar_custo(barbearia_id: str, nome: str | None, valor_centavos: int) -> str:
    with com_barbearia(barbearia_id):
        custo = Custo.objects.create(
            barbearia_id=barbearia_id, nome=(nome or "").strip() or None,
            valor_centavos=valor_centavos,
        )
    return str(custo.id)


def apagar_custo(barbearia_id: str, custo_id: str) -> bool:
    with com_barbearia(barbearia_id):
        apagados, _ = Custo.objects.filter(id=custo_id).delete()
    return apagados > 0
