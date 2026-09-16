import time
import uuid

import pytest
from django.db import connections

from app.services.zelador import alarmar_e_podar
from tenant.config import ZELADOR_DIAS_DE_HISTORICO

# "owner" entrava so' porque o `limpar_banco` autouse do conftest.py (TRUNCATE
# das tabelas de tenant) roda pra' todo teste com `django_db`, e a databases
# dele precisa estar liberada pra' aquele fixture nao estourar
# `DatabaseOperationForbidden`.
#
# "default" e novidade, e nao e' detalhe de teste: o zelador PASSOU a tocar o
# `brutus` de verdade. Alem do historico da Evolution, ele agora poda as
# "mensagens nao enviadas" do painel — tabela de tenant, com RLS, lida pela
# conexao de runtime.
pytestmark = pytest.mark.django_db(
    databases=["default", "owner", "evolution"], transaction=True,
)

_DDL = """
DROP TABLE IF EXISTS "MessageUpdate";
DROP TABLE IF EXISTS "Message";
CREATE TABLE "Message" (
    id TEXT PRIMARY KEY,
    "messageTimestamp" BIGINT NOT NULL
);
CREATE TABLE "MessageUpdate" (
    id TEXT PRIMARY KEY,
    "messageId" TEXT NOT NULL REFERENCES "Message"(id),
    status TEXT NOT NULL
);
"""


@pytest.fixture(autouse=True)
def _tabelas_evolution():
    """`Message`/`MessageUpdate` MINIMAS — so' as colunas que
    `alarmar_e_podar` le. Aproximacao DELIBERADA: quem cria o schema real e'
    a propria Evolution, via as migracoes dela, e ele nao mora (nem deve
    morar) neste repositorio — aqui so' provamos que a NOSSA consulta faz o
    que promete contra uma tabela no MESMO formato.

    Recriada na ENTRADA de cada teste, mesma filosofia do `limpar_banco` do
    conftest.py: se a corrida anterior morreu no meio, a proxima nao herda
    tabela suja."""
    with connections["evolution"].cursor() as cur:
        cur.execute(_DDL)
    yield


def _mensagem(ts_epoch_s: int) -> str:
    id_ = str(uuid.uuid4())
    with connections["evolution"].cursor() as cur:
        cur.execute(
            'INSERT INTO "Message" (id, "messageTimestamp") VALUES (%s, %s)',
            [id_, ts_epoch_s],
        )
    return id_


def _update(message_id: str, status: str) -> None:
    with connections["evolution"].cursor() as cur:
        cur.execute(
            'INSERT INTO "MessageUpdate" (id, "messageId", status) VALUES (%s, %s, %s)',
            [str(uuid.uuid4()), message_id, status],
        )


def _existe_message(id_: str) -> bool:
    with connections["evolution"].cursor() as cur:
        cur.execute('SELECT 1 FROM "Message" WHERE id = %s', [id_])
        return cur.fetchone() is not None


_AGORA = int(time.time())
_RECENTE = _AGORA - 86_400  # 1 dia atras
_VELHO = _AGORA - (ZELADOR_DIAS_DE_HISTORICO + 1) * 86_400  # passou do prazo


def test_conta_recusados_corretamente():
    m1, m2, m3 = _mensagem(_RECENTE), _mensagem(_RECENTE), _mensagem(_RECENTE)
    _update(m1, "ERROR")
    _update(m2, "ERROR")
    _update(m3, "DELIVERY_ACK")

    resultado = alarmar_e_podar()
    assert resultado["recusados"] == 2


def test_sem_recusado_conta_zero():
    m1 = _mensagem(_RECENTE)
    _update(m1, "DELIVERY_ACK")

    resultado = alarmar_e_podar()
    assert resultado["recusados"] == 0


def test_poda_o_que_passou_do_prazo_e_preserva_o_recente():
    velho = _mensagem(_VELHO)
    _update(velho, "DELIVERY_ACK")
    recente = _mensagem(_RECENTE)
    _update(recente, "DELIVERY_ACK")

    resultado = alarmar_e_podar()

    assert resultado["podados_message"] == 1
    assert resultado["podados_message_update"] == 1
    assert not _existe_message(velho)
    assert _existe_message(recente)


def test_nao_poda_nada_quando_tudo_esta_dentro_do_prazo():
    recente = _mensagem(_RECENTE)
    _update(recente, "DELIVERY_ACK")

    resultado = alarmar_e_podar()

    assert resultado["podados_message"] == 0
    assert resultado["podados_message_update"] == 0
    assert _existe_message(recente)


def test_message_update_e_apagado_antes_de_message_sem_violar_a_fk():
    """Se a ordem estivesse trocada (apagar `Message` primeiro), o DELETE
    estouraria uma violacao de chave estrangeira — `MessageUpdate.messageId`
    referencia `Message.id`. Este teste passa SO' se a ordem estiver certa."""
    velho = _mensagem(_VELHO)
    _update(velho, "ERROR")

    resultado = alarmar_e_podar()  # nao pode lancar

    assert resultado["podados_message"] == 1
    assert resultado["podados_message_update"] == 1


def test_loga_o_alarme_quando_ha_recusado(caplog):
    m1 = _mensagem(_RECENTE)
    _update(m1, "ERROR")

    with caplog.at_level("WARNING"):
        alarmar_e_podar()

    assert "1 ENVIO(S) RECUSADO(S)" in caplog.text


def test_loga_info_quando_nao_ha_recusado(caplog):
    m1 = _mensagem(_RECENTE)
    _update(m1, "DELIVERY_ACK")

    with caplog.at_level("INFO"):
        alarmar_e_podar()

    assert "nenhum envio recusado" in caplog.text


# ------------------------------------------------- as "nao enviadas" do painel


def test_poda_nao_enviadas_antigas_e_preserva_as_recentes(cenario):
    """O contador do painel precisa poder voltar a zero. Sem poda ele so
    cresceria, e um numero que nunca zera deixa de ser informacao."""
    import uuid
    from datetime import timedelta

    from django.utils import timezone

    from app.services.zelador import _podar_nao_enviadas
    from tenant.config import ZELADOR_DIAS_DE_HISTORICO
    from tenant.models import MensagemNaoEnviada
    from tenant.rls import com_barbearia

    b = cenario["brutus"]
    agora = timezone.now()
    for nome, quando in (
        ("Velha", agora - timedelta(days=ZELADOR_DIAS_DE_HISTORICO + 1)),
        ("Nova", agora - timedelta(hours=1)),
    ):
        MensagemNaoEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, tipo="CONFIRMACAO",
            cliente_nome=nome, criado_em=quando,
        )

    assert _podar_nao_enviadas() == 1

    with com_barbearia(b.id):
        assert [m.cliente_nome for m in MensagemNaoEnviada.objects.all()] == ["Nova"]


def test_poda_conversas_paradas_e_preserva_as_vivas_e_as_mudas(cenario):
    from datetime import timedelta

    from django.utils import timezone

    from app.services.zelador import _podar_conversas
    from tenant.config import BOT_CONVERSA_GUARDADA_DIAS
    from tenant.models import ConversaWhatsapp
    from tenant.rls import com_barbearia

    b = cenario["brutus"]
    agora = timezone.now()
    velha = agora - timedelta(days=BOT_CONVERSA_GUARDADA_DIAS + 1)
    for numero, atualizado, mudo in (
        ("83900000001", velha, None),                         # some
        ("83900000002", agora - timedelta(hours=1), None),    # fica: recente
        # Fica: parada ha dias, mas alguem da barbearia ainda esta falando
        # com essa pessoa. Apagar a linha faria o bot voltar a atropelar.
        ("83900000003", velha, agora + timedelta(hours=2)),
    ):
        ConversaWhatsapp.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=numero,
            atualizado_em=atualizado, mudo_ate=mudo,
        )

    assert _podar_conversas() == 1

    with com_barbearia(b.id):
        assert sorted(ConversaWhatsapp.objects.values_list("whatsapp", flat=True)) == [
            "83900000002", "83900000003",
        ]
