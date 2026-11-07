"""Grupos do catalogo (Cabelo, Barba, Combos...).

A regra que tudo aqui protege e' "tudo ou nada": ou a casa nao tem grupo
nenhum e a lista e' solta, ou tem ao menos um e TODO servico esta dentro de
algum. Nunca "3 dentro e 10 espalhados". Por isso:

- criar o PRIMEIRO grupo puxa o catalogo inteiro para ele;
- apagar um grupo com servicos exige dizer para qual grupo eles vao;
- apagar o ULTIMO grupo solta todos de novo.
"""

import uuid

from tenant.identidade import como_uuid
from tenant.models import ICONES_DE_GRUPO, GrupoServico, Servico
from tenant.rls import com_barbearia


def icone_valido(icone) -> bool:
    return icone is None or icone in ICONES_DE_GRUPO


def listar(barbearia_id: str) -> list[dict]:
    with com_barbearia(barbearia_id):
        return list(
            GrupoServico.objects.order_by("ordem", "nome").values("id", "nome", "icone", "ordem")
        )


def existe(grupo_id) -> bool:
    """Chamar DENTRO de `com_barbearia`: o RLS e' quem faz um grupo de outra
    casa parecer inexistente."""
    alvo = como_uuid(str(grupo_id)) if grupo_id is not None else None
    return alvo is not None and GrupoServico.objects.filter(id=alvo).exists()


def tem_grupos() -> bool:
    """Tambem so' dentro de `com_barbearia`."""
    return GrupoServico.objects.exists()


def criar(barbearia_id: str, nome: str, icone: str | None) -> dict:
    with com_barbearia(barbearia_id):
        if GrupoServico.objects.filter(nome=nome).exists():
            return {"tipo": "repetido"}

        primeiro = not GrupoServico.objects.exists()
        ultimo = GrupoServico.objects.order_by("-ordem").values("ordem").first()
        novo_id = uuid.uuid4()
        GrupoServico.objects.create(
            id=novo_id, barbearia_id=barbearia_id, nome=nome, icone=icone,
            ordem=(ultimo["ordem"] if ultimo else -1) + 1,
        )
        if primeiro:
            # O catalogo inteiro, ativo e inativo: um desativado que voltasse
            # depois sem grupo quebraria a regra pela porta dos fundos.
            Servico.objects.filter(grupo__isnull=True).update(grupo_id=novo_id)
        return {"tipo": "ok", "id": str(novo_id)}


def atualizar(barbearia_id: str, grupo_id: str, campos: dict) -> dict:
    with com_barbearia(barbearia_id):
        atual = GrupoServico.objects.filter(id=grupo_id).values("nome").first()
        if atual is None:
            return {"tipo": "nao_encontrado"}

        novo_nome = campos.get("nome")
        if novo_nome is not None and novo_nome != atual["nome"]:
            if GrupoServico.objects.filter(nome=novo_nome).exists():
                return {"tipo": "repetido"}

        GrupoServico.objects.filter(id=grupo_id).update(**campos)
        return {"tipo": "ok"}


def apagar(barbearia_id: str, grupo_id: str, mover_para: str | None) -> dict:
    with com_barbearia(barbearia_id):
        if not GrupoServico.objects.filter(id=grupo_id).exists():
            return {"tipo": "nao_encontrado"}

        outros = GrupoServico.objects.exclude(id=grupo_id)
        servicos = Servico.objects.filter(grupo_id=grupo_id)

        if not outros.exists():
            # O ultimo grupo: a casa volta para a lista solta.
            servicos.update(grupo_id=None)
        elif servicos.exists():
            alvo = como_uuid(mover_para) if mover_para else None
            if alvo is None or alvo == como_uuid(grupo_id) or not outros.filter(id=alvo).exists():
                return {"tipo": "falta_destino"}
            servicos.update(grupo_id=alvo)

        GrupoServico.objects.filter(id=grupo_id).delete()
        return {"tipo": "ok"}
