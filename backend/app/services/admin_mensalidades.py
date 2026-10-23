"""A mensalidade vista pelo admin da plataforma: a lista de todas as
barbearias, os ajustes de cada assinatura e as tres decisoes sobre um
pagamento (confirmar, recusar, registrar na mao).

Tudo pelo alias `admin` (`Assinatura` e `Cobranca` ficam fora do RLS e o
`brutus_app` so le). A conta da situacao e' a de `ler_situacao`, a mesma da
trava do painel, com a mesma pergunta de `operacoes.cobravel` no lugar do
`isenta`; aqui ela roda sobre dados lidos em bloco, para a lista nao fazer
tres consultas por barbearia."""

SEM_VALOR = "Defina o valor da mensalidade antes de cobrar."

from django.db import transaction
from django.utils import timezone

from tenant.models import (
    Assinatura,
    Barbearia,
    Barbeiro,
    Cobranca,
    MotivoCobranca,
    StatusCobranca,
)
from tenant.rls import com_barbearia_admin

from .mensalidade import operacoes
from .mensalidade.datas import dia_de_vencimento_para, mes_seguinte
from .mensalidade.situacao import Situacao, hoje_em_sao_paulo, ler_situacao

ALIAS = "admin"


def _data(d):
    return d.isoformat() if d else None


def _nome_de_quem_avisou(barbearia_id, barbeiro_id):
    """O barbeiro e' tabela de tenant (RLS): so' se le dentro da barbearia."""
    if barbeiro_id is None:
        return None
    with com_barbearia_admin(barbearia_id):
        return (
            Barbeiro.objects.using(ALIAS)
            .filter(id=barbeiro_id)
            .values_list("nome", flat=True)
            .first()
        )


def _linhas(agora, barbearia_id=None):
    hoje = hoje_em_sao_paulo(agora)
    barbearias = Barbearia.objects.using(ALIAS).order_by("nome", "id")
    assinaturas = Assinatura.objects.using(ALIAS)
    mensalidades = Cobranca.objects.using(ALIAS).filter(motivo=MotivoCobranca.MENSALIDADE)
    if barbearia_id is not None:
        barbearias = barbearias.filter(id=barbearia_id)
        assinaturas = assinaturas.filter(pk=barbearia_id)
        mensalidades = mensalidades.filter(barbearia_id=barbearia_id)

    por_assinatura = {a.barbearia_id: a for a in assinaturas}
    informadas = {
        c.barbearia_id: c
        for c in mensalidades.filter(status=StatusCobranca.ABERTA).exclude(informada_em=None)
    }
    # A mais recente primeiro; a primeira de cada barbearia e' a ultima paga.
    ultimas = {}
    for c in mensalidades.filter(status=StatusCobranca.PAGA).order_by("-paga_em", "-criada_em"):
        ultimas.setdefault(c.barbearia_id, c)

    linhas = []
    for b in barbearias:
        a = por_assinatura.get(b.id)
        info = informadas.get(b.id)
        ultima = ultimas.get(b.id)
        if a is None:
            # Dado torto: vale como isenta (mesma regra da trava).
            leitura = ler_situacao(
                barbearia_ativa=b.ativo, isenta=True, nunca_bloquear=False,
                paga_ate=hoje, aviso_em=None, hoje=hoje, agora=agora,
            )
        else:
            leitura = ler_situacao(
                barbearia_ativa=b.ativo, isenta=not operacoes.cobravel(a),
                nunca_bloquear=a.nunca_bloquear, paga_ate=a.paga_ate,
                aviso_em=info.informada_em if info else None, hoje=hoje, agora=agora,
            )
        linhas.append({
            "barbeariaId": str(b.id),
            "nome": b.nome,
            "tipo": b.tipo,
            "ativo": b.ativo,
            "situacao": str(leitura.situacao),
            "dias": leitura.dias,
            "bloqueiaEm": _data(leitura.bloqueia_em),
            "valorCentavos": a.valor_centavos if a else None,
            "pagaAte": _data(a.paga_ate) if a else None,
            "isenta": a.isenta if a else True,
            "nuncaBloquear": a.nunca_bloquear if a else False,
            "informada": {
                "cobrancaId": str(info.id),
                "valorCentavos": info.valor_centavos,
                "em": info.informada_em.isoformat(),
                "porNome": _nome_de_quem_avisou(b.id, info.informada_por_id),
            } if info else None,
            "ultimaPaga": {
                "pagaEm": ultima.paga_em.isoformat() if ultima.paga_em else None,
                "valorCentavos": ultima.valor_centavos,
                "como": ultima.como_foi_paga,
            } if ultima else None,
        })
    return linhas


def listar(*, agora=None):
    agora = agora or timezone.now()
    linhas = _linhas(agora)
    return {
        "barbearias": linhas,
        "contadores": {
            "informadas": sum(1 for x in linhas if x["informada"]),
            "atrasadas": sum(1 for x in linhas if x["situacao"] == Situacao.ATRASADA),
            "bloqueadas": sum(1 for x in linhas if x["situacao"] == Situacao.BLOQUEADA),
        },
    }


def linha(barbearia_id, *, agora=None):
    """A linha de uma barbearia, ou None se ela nao existe."""
    achadas = _linhas(agora or timezone.now(), barbearia_id)
    return achadas[0] if achadas else None


def atualizar(barbearia_id, campos, *, agora=None):
    """Aplica o subconjunto de `campos` (ja validados) na assinatura, criando
    a linha se faltar. False se a barbearia nao existe; levanta
    `RecusaDaMensalidade` (e nada muda) ao ligar a cobranca com valor zero."""
    agora = agora or timezone.now()
    with transaction.atomic(using=ALIAS):
        if not Barbearia.objects.using(ALIAS).filter(id=barbearia_id).exists():
            return False
        # Mesma trava das operacoes: um "ja paguei" correndo junto nao pode
        # passar entre o que lemos e o que cancelamos.
        assinatura = operacoes._travar_assinatura(barbearia_id)
        if assinatura is None:
            hoje = hoje_em_sao_paulo(agora)
            assinatura = Assinatura.objects.using(ALIAS).create(
                barbearia_id=barbearia_id, valor_centavos=0,
                dia_de_vencimento=dia_de_vencimento_para(hoje), paga_ate=hoje,
                isenta=True,
            )
        mudou_valor = False
        fim_do_ciclo = False
        voltou_a_cobrar = False
        if "valorCentavos" in campos and campos["valorCentavos"] != assinatura.valor_centavos:
            assinatura.valor_centavos = campos["valorCentavos"]
            mudou_valor = True
        if "isenta" in campos and campos["isenta"] != assinatura.isenta:
            assinatura.isenta = campos["isenta"]
            if assinatura.isenta:
                fim_do_ciclo = True
            else:
                voltou_a_cobrar = True
        if "isenta" in campos and not campos["isenta"] and assinatura.valor_centavos <= 0:
            # Cobrar zero nao tem Pix: a barbearia leria isenta mas o admin
            # veria a caixa desmarcada. Melhor dizer na hora.
            raise operacoes.RecusaDaMensalidade(SEM_VALOR)
        if "nuncaBloquear" in campos:
            assinatura.nunca_bloquear = campos["nuncaBloquear"]
        if "pagaAte" in campos:
            fim_do_ciclo = fim_do_ciclo or campos["pagaAte"] != assinatura.paga_ate
            assinatura.paga_ate = campos["pagaAte"]
            assinatura.dia_de_vencimento = dia_de_vencimento_para(campos["pagaAte"])
        elif voltou_a_cobrar:
            # O `paga_ate` de quem era isenta ficou parado no tempo (meses
            # atras, as vezes): usa-lo trancaria o painel no ato. Ligar a
            # cobranca sem data recomeca como barbearia nova, um mes a frente.
            hoje = hoje_em_sao_paulo(agora)
            dia = dia_de_vencimento_para(hoje)
            assinatura.paga_ate = mes_seguinte(hoje, dia)
            assinatura.dia_de_vencimento = dia
        assinatura.atualizada_em = agora
        assinatura.save(using=ALIAS)
        if fim_do_ciclo:
            # Isenta ou com o `paga_ate` movido na mao: o ciclo da cobranca
            # aberta acabou, avisada ou nao.
            operacoes.cancelar_aberta(barbearia_id)
        elif mudou_valor or voltou_a_cobrar:
            # O Pix aberto e ainda nao avisado carrega o valor velho: some, e a
            # proxima leitura do painel abre outro com o valor novo. O ja
            # avisado fica, porque o dono pode ter pago aquele valor.
            operacoes._abertas_da_mensalidade(barbearia_id).filter(
                informada_em=None
            ).update(status=StatusCobranca.CANCELADA)
    return True


def registrar(barbearia_id, *, paga_ate=None, valor_centavos, observacao, agora=None):
    """Levanta `RecusaDaMensalidade`; False se a barbearia nao existe."""
    agora = agora or timezone.now()
    if not Barbearia.objects.using(ALIAS).filter(id=barbearia_id).exists():
        return False
    operacoes.registrar_manual(
        barbearia_id, paga_ate=paga_ate, valor_centavos=valor_centavos,
        observacao=observacao, agora=agora,
    )
    return True



def confirmar(cobranca_id, *, agora=None):
    agora = agora or timezone.now()
    cobranca = operacoes.confirmar(cobranca_id, agora=agora)
    return cobranca.barbearia_id


def recusar(cobranca_id, *, agora=None):
    agora = agora or timezone.now()
    cobranca = operacoes.recusar(cobranca_id, agora=agora)
    return cobranca.barbearia_id
