import uuid

from django.db.models import Count, F, Max, Q

from app.services.convite import gerar_convite
from tenant.datas import como_utc, formatar_dia_curto
from tenant.models import Agendamento, Barbeiro
from tenant.rls import com_barbearia

# ---------------------------------------------------------------- recusas puras


def pode_desativar(
    *, eh_eu_mesmo: bool, papel: str, donos_ativos: int,
    agendamentos_futuros: int, proximo_em,
) -> str | None:
    """Porte de `podeDesativar` (front/src/lib/equipe.ts). Ordem por
    proximidade de quem le: quem tenta se desativar precisa ouvir isso
    primeiro, nao a contagem de agendamento de outra pessoa."""
    if eh_eu_mesmo:
        return "Você não pode se desativar — pede para outro dono fazer isso."
    if papel == "DONO" and donos_ativos <= 1:
        return "Esse é o único dono ativo. Promove outra pessoa antes."
    if agendamentos_futuros > 0:
        quando = f" até {formatar_dia_curto(proximo_em)}" if proximo_em else ""
        return (
            f"Tem {agendamentos_futuros} horário(s) marcado(s){quando}. "
            "Cancela ou remarca antes de desativar."
        )
    return None


def pode_rebaixar(*, donos_ativos: int) -> str | None:
    if donos_ativos <= 1:
        return "Esse é o único dono ativo. Promove outra pessoa antes de rebaixar."
    return None


# ---------------------------------------------------------------- leitura interna


def _contar_donos_ativos(barbearia_id: str) -> int:
    """DEVE rodar dentro de um `com_barbearia` ja aberto pelo chamador — usa
    `select_for_update`, que precisa da transacao real que `com_barbearia`
    abre com `atomic(durable=True)`. Trava as LINHAS de Barbeiro (nao a de
    Barbearia — o papel `brutus_app` nao tem UPDATE ali de proposito) para
    que duas desativacoes/rebaixamentos simultaneos nao leiam '2' os dois e
    deixem a barbearia com zero donos ativos."""
    return Barbeiro.objects.select_for_update().filter(
        barbearia_id=barbearia_id, papel="DONO", ativo=True
    ).count()


def _agenda_futura_de(barbeiro_id: str, agora) -> dict:
    r = Agendamento.objects.filter(
        barbeiro_id=barbeiro_id, status="CONFIRMADO", inicio__gt=agora
    ).aggregate(quantos=Count("id"), proximo_em=Max("inicio"))
    return {"quantos": r["quantos"], "proximo_em": r["proximo_em"]}


def _carregar(barbeiro_id: str) -> dict | None:
    return Barbeiro.objects.filter(id=barbeiro_id).values(
        "id", "nome", "papel", "ativo", "whatsapp", "token_version"
    ).first()


# ---------------------------------------------------------------- crud do painel


def listar(barbearia_id: str, agora) -> list[dict]:
    with com_barbearia(barbearia_id):
        barbeiros = list(
            Barbeiro.objects.annotate(
                servicos=Count(
                    "vinculos", filter=Q(vinculos__ativo=True, vinculos__servico__ativo=True)
                ),
                expediente=Count("horarios"),
            )
            .order_by("-ativo", "ordem")
            .values(
                "id", "nome", "whatsapp", "papel", "ativo", "desativado_em",
                "senha_hash", "convite_expira_em", "servicos", "expediente",
            )
        )
        futuros = dict(
            Agendamento.objects.filter(status="CONFIRMADO", inicio__gt=agora)
            .values("barbeiro_id")
            .annotate(n=Count("id"))
            .values_list("barbeiro_id", "n")
        )

    saida = []
    for b in barbeiros:
        # `como_utc`: a coluna e' `timestamp WITHOUT time zone`, e comparar o
        # valor cru (naive) contra `agora` (aware) estoura em Python — mesmo
        # que o filtro por queryset (`_agenda_futura_de` abaixo) va bem, porque
        # ali quem compara e' o Postgres, nao o Python.
        convite_expira_em = como_utc(b["convite_expira_em"])
        convite_expirado = (
            b["senha_hash"] is None
            and convite_expira_em is not None
            and convite_expira_em < agora
        )
        saida.append(
            {
                "id": b["id"], "nome": b["nome"], "whatsapp": b["whatsapp"],
                "papel": b["papel"], "ativo": b["ativo"], "desativado_em": b["desativado_em"],
                "tem_senha": b["senha_hash"] is not None,
                "convite_expirado": convite_expirado,
                # Os MESMOS filtros de `listar_para_painel` dos servicos:
                # vinculo ativo E servico ativo. Zero em qualquer um dos dois
                # e' o aviso de que o barbeiro sumiu da tela do cliente.
                "servicos": b["servicos"], "expediente": b["expediente"],
                "agendamentos_futuros": futuros.get(b["id"], 0),
            }
        )
    return saida


def criar(barbearia_id: str, nome: str, whatsapp: str, papel: str) -> dict:
    with com_barbearia(barbearia_id):
        # SEM filtrar por `ativo`: o indice unico e' `[barbeariaId, whatsapp]`
        # e nao distingue desativado — sem esta checagem o erro viria do
        # Postgres como 500.
        existente = Barbeiro.objects.filter(whatsapp=whatsapp).values("nome", "ativo").first()
        if existente:
            return {"tipo": "repetido", "nome": existente["nome"], "ativo": existente["ativo"]}

        convite = gerar_convite()
        ultimo = Barbeiro.objects.order_by("-ordem").values("ordem").first()
        novo_id = str(uuid.uuid4())
        Barbeiro.objects.create(
            id=novo_id, barbearia_id=barbearia_id, nome=nome, whatsapp=whatsapp, papel=papel,
            # Nasce SEM senha: quem entra e' quem abrir o link do convite.
            senha_hash=None,
            convite_token_hash=convite["hash"], convite_expira_em=convite["expira_em"],
            ordem=(ultimo["ordem"] if ultimo else -1) + 1,
        )
        return {"tipo": "ok", "id": novo_id, "convite": convite}


def atualizar(barbearia_id: str, sessao: dict, barbeiro_id: str, campos: dict) -> dict:
    """`campos` ja chega normalizado (whatsapp) e so com o que mudou, em
    nomes de coluna Django (nome/whatsapp/papel)."""
    with com_barbearia(barbearia_id):
        atual = _carregar(barbeiro_id)
        if atual is None:
            return {"tipo": "nao_encontrado"}

        novo_papel = campos.get("papel")
        # `barbeiro.ativo` na condicao: rebaixar um dono JA desativado nao
        # pode deixar a barbearia orfa (ele nao conta em `_contar_donos_ativos`
        # de qualquer forma), mas tambem nao precisa da recusa — sem isso a
        # casa com um dono ativo e um desativado recusava mexer no
        # desativado dizendo "e' o unico dono ativo", que ele nao e'.
        if novo_papel == "BARBEIRO" and atual["papel"] == "DONO" and atual["ativo"]:
            recusa = pode_rebaixar(donos_ativos=_contar_donos_ativos(barbearia_id))
            if recusa:
                return {"tipo": "recusado", "erro": recusa}

        novo_whatsapp = campos.get("whatsapp")
        if novo_whatsapp is not None and novo_whatsapp != atual["whatsapp"]:
            ja_tem = Barbeiro.objects.filter(whatsapp=novo_whatsapp).values("nome", "ativo").first()
            if ja_tem:
                msg = (
                    f"Esse celular já é do {ja_tem['nome']}."
                    if ja_tem["ativo"]
                    else f"Esse celular é do {ja_tem['nome']}, que está desativado."
                )
                return {"tipo": "recusado", "erro": msg}

        # O `papel` viaja no token: rebaixar sem invalidar deixaria alcance
        # de dono valendo por ate 12h. O celular e' o login, entao muda-lo
        # tambem refaz a identidade da conta. Trocar so o NOME nao derruba
        # nada — seria expulsar o barbeiro do painel por causa de um acento.
        mudou_sessao = (
            (novo_papel is not None and novo_papel != atual["papel"])
            or (novo_whatsapp is not None and novo_whatsapp != atual["whatsapp"])
        )

        atualizacao = dict(campos)
        if mudou_sessao:
            atualizacao["token_version"] = F("token_version") + 1
        Barbeiro.objects.filter(id=barbeiro_id).update(**atualizacao)
        return {"tipo": "ok"}


def desativar(barbearia_id: str, sessao: dict, barbeiro_id: str, agora) -> dict:
    with com_barbearia(barbearia_id):
        atual = _carregar(barbeiro_id)
        if atual is None:
            return {"tipo": "nao_encontrado"}

        agenda = _agenda_futura_de(barbeiro_id, agora)
        recusa = pode_desativar(
            eh_eu_mesmo=(atual["id"] == sessao["sub"]),
            papel=atual["papel"],
            donos_ativos=_contar_donos_ativos(barbearia_id),
            agendamentos_futuros=agenda["quantos"],
            proximo_em=agenda["proximo_em"],
        )
        if recusa:
            return {"tipo": "recusado", "erro": recusa}

        Barbeiro.objects.filter(id=barbeiro_id).update(
            ativo=False, desativado_em=agora,
            # Derruba a sessao na hora — sem isto, quem saiu da equipe
            # continuaria dentro do painel por ate 12 horas.
            token_version=F("token_version") + 1,
        )
        return {"tipo": "ok"}


def reativar(barbearia_id: str, barbeiro_id: str) -> dict:
    with com_barbearia(barbearia_id):
        if not Barbeiro.objects.filter(id=barbeiro_id).exists():
            return {"tipo": "nao_encontrado"}

        # NAO incrementa token_version: quem estava desativado nao tem
        # sessao para derrubar. Volta como estava, inclusive sem senha.
        Barbeiro.objects.filter(id=barbeiro_id).update(ativo=True, desativado_em=None)
        return {"tipo": "ok"}


def reconvidar(barbearia_id: str, barbeiro_id: str) -> dict:
    with com_barbearia(barbearia_id):
        atual = _carregar(barbeiro_id)
        if atual is None:
            return {"tipo": "nao_encontrado"}
        if not atual["ativo"]:
            # Quem saiu nao recebe "voce entrou na equipe" pelo WhatsApp — o
            # convite ainda deixaria criar senha, e o login seria recusado
            # depois na conferencia de `ativo`, entao a mensagem seria so engano.
            return {"tipo": "desativado"}

        convite = gerar_convite()
        Barbeiro.objects.filter(id=barbeiro_id).update(
            senha_hash=None,
            convite_token_hash=convite["hash"], convite_expira_em=convite["expira_em"],
            token_version=F("token_version") + 1,
        )
        return {"tipo": "ok", "nome": atual["nome"], "whatsapp": atual["whatsapp"], "convite": convite}
