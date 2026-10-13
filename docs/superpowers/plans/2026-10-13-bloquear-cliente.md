# Bloquear cliente — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a equipe bloqueia um cliente (número e aparelho) para ele não conseguir mais marcar pelo site, sem que ele saiba; o dono vê e desbloqueia.

**Architecture:** dois campos no `Cliente` (`bloqueado_em`, `bloqueado_por`) e um no `Agendamento` (`aparelho`, a marca do navegador que veio por cookie httpOnly). Um serviço novo (`app/services/clientes_bloqueados.py`) concentra as regras; a rota pública só consulta `esta_bloqueado` antes de `marcar()`; o painel ganha bloquear (a partir de um agendamento), listar e desbloquear. No front, botão na Agenda e lista no fim da Equipe.

**Tech Stack:** Django + DRF + Postgres com RLS (back, pytest); Next 16 + React + Tailwind v4 (front, vitest).

**Spec:** `docs/superpowers/specs/2026-10-13-bloquear-cliente-design.md`

## Global Constraints

- Frase da recusa, exata: `Não foi possível concluir o agendamento. Chama {o_lugar}: {formatar(contato)}` — `o_lugar` de `palavras(tipo)["o_lugar"]` ("a barbearia" / "o estúdio" / "o espaço"), `contato` = `barbearia.whatsapp_contato`. Status **422**.
- Cookie: nome `aparelho`, valor `secrets.token_urlsafe(16)`, `max_age=2*365*24*3600`, `path="/"`, `httponly=True`, `samesite="Lax"`, `secure=not settings.DEBUG`, host-only (sem `domain`).
- A recusa vem DEPOIS das checagens existentes da rota pública (serializer, `normalizar`, `numero_existe`) e ANTES de `marcar()`. Nada é gravado na recusa.
- O painel (`POST /api/painel/agendamentos`) não confere bloqueio.
- Bloquear cancela os `CONFIRMADO` com `inicio > agora` do cliente, com qualquer barbeiro, status `CANCELADO_BARBEIRO`, **sem** WhatsApp ao cliente; depois do commit chama `lista_do_dia.avisar_mudanca(barbearia_id, barbeiro_id, agora, cancelados=[(id, inicio), ...])` uma vez por barbeiro.
- Bloquear quem já está bloqueado: não muda nada (não cancela de novo), responde ok.
- Desbloquear não restaura horários.
- Barbeiro só bloqueia a partir de agendamento dele (404 no do colega); listar/desbloquear são `ExigeDono` (403 com "Só o dono vê os clientes bloqueados.").
- Rodar testes do back: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider <alvo>`. Do front: `docker exec Marcai-front-app sh -c 'cd /app && npx vitest run <alvo>'` e `npx tsc --noEmit`.

## Review Focus

1. Aparelho que marcou com o número ANTES do bloqueio, depois tenta com número novo → recusado (a consulta, não uma cópia, é que cobre) — teste na Tarefa 2.
2. Cliente bloqueado numa barbearia marca com o mesmo número em OUTRA → passa — teste na Tarefa 2.
3. Primeiro agendamento sem cookie: a resposta 201 traz `Set-Cookie: aparelho` e o agendamento grava o mesmo valor; com cookie já presente, não troca o valor — teste na Tarefa 3.
4. Bloquear não toca horários passados nem os já cancelados — teste na Tarefa 2.
5. `id` de agendamento inexistente/torto em bloquear → 404, nunca 500 — teste na Tarefa 4.

---

### Task 1: Campos no banco

**Files:**
- Modify: `backend/tenant/models.py` (classe `Cliente`, ~linha 385; classe `Agendamento`, ~linha 415)
- Create: `backend/tenant/migrations/0012_cliente_bloqueado.py`

**Interfaces:**
- Produces: `Cliente.bloqueado_em: DateTimeField(null)`, `Cliente.bloqueado_por: FK Barbeiro (null, SET_NULL, related_name="+")`, `Agendamento.aparelho: TextField(null)`.

- [ ] **Step 1: Acrescentar os campos ao modelo**

Em `Cliente`, depois de `criado_em`:

```python
    # Bloqueado = `bloqueado_em` preenchido (spec 2026-10-13). O site recusa
    # marcar com este numero, e com qualquer aparelho que ja' marcou com ele.
    bloqueado_em = models.DateTimeField(null=True, blank=True)
    bloqueado_por = models.ForeignKey(
        "Barbeiro", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
```

Em `Agendamento`, depois de `lembrete_enviado_em`:

```python
    # A marca do navegador que marcou pelo site (cookie `aparelho`). Nulo
    # para o painel, o bot e tudo que veio antes de 13/10/2026.
    aparelho = models.TextField(null=True, blank=True)
```

- [ ] **Step 2: Gerar a migration**

Run: `docker exec Marcai-back-api python manage.py makemigrations tenant -n cliente_bloqueado`
Expected: cria `0012_cliente_bloqueado.py` com três `AddField`. Abrir e conferir que só há `AddField` (sem GRANT: `cliente` e `agendamento` têm GRANT de tabela para `brutus_app`, que vale para coluna nova).

- [ ] **Step 3: Aplicar e rodar a suíte inteira**

Run: `docker exec Marcai-back-api python manage.py migrate` e `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider`
Expected: tudo passa (inclusive `test_toda_tabela_que_aponta_para_barbearia_sai_junto` — nenhuma tabela nova).

- [ ] **Step 4: Commit**

```bash
git add backend/tenant/models.py backend/tenant/migrations/0012_cliente_bloqueado.py
git commit -m "bloquear cliente: campos no cliente e a marca do aparelho no agendamento"
```

### Task 2: O serviço

**Files:**
- Create: `backend/app/services/clientes_bloqueados.py`
- Test: `tests/test_clientes_bloqueados.py`

**Interfaces:**
- Consumes: campos da Tarefa 1.
- Produces:
  - `esta_bloqueado(barbearia_id, whatsapp: str, aparelho: str | None) -> bool`
  - `previa(barbearia_id, agendamento_id, filtro_barbeiro_id, agora: datetime) -> dict | None` → `{"clienteId": str, "nome": str, "whatsapp": str, "horarios": int, "bloqueado": bool}`
  - `bloquear(barbearia_id, agendamento_id, filtro_barbeiro_id, por_id, agora: datetime) -> list[tuple] | None` → `[(barbeiro_id, agendamento_id, inicio), ...]` cancelados (vazio se já estava bloqueado); `None` = não encontrado.
  - `listar(barbearia_id) -> list[dict]` → `{"id", "nome", "whatsapp", "bloqueadoEm", "bloqueadoPor"}`, mais recente primeiro.
  - `desbloquear(barbearia_id, cliente_id) -> bool`

- [ ] **Step 1: Escrever os testes**

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.clientes_bloqueados import (
    bloquear, desbloquear, esta_bloqueado, listar, previa,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

AGORA = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _cliente(barbearia_id, whatsapp="11977778888", nome="Maria"):
    from tenant.models import Cliente

    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome, whatsapp=whatsapp,
    )


def _agendamento(barbearia_id, barbeiro, cliente, inicio, status="CONFIRMADO", aparelho=None):
    from tenant.models import Agendamento, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico.nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status, aparelho=aparelho,
    )


def _status(agendamento):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").get(id=agendamento.id).status


# ------------------------------------------------------------ esta_bloqueado


def test_numero_livre_nao_esta_bloqueado(cenario):
    b = cenario["brutus"]
    _cliente(b.id)
    assert esta_bloqueado(b.id, "11977778888", None) is False


def test_numero_bloqueado_esta_bloqueado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    a = _agendamento(b.id, zeca, _cliente(b.id), AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)
    assert esta_bloqueado(b.id, "11977778888", None) is True


def test_numero_novo_no_aparelho_de_um_bloqueado_esta_bloqueado(cenario):
    """O aparelho marcou com o numero ANTES do bloqueio; depois ela troca de
    numero no mesmo celular."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=3), aparelho="cel-da-maria")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert esta_bloqueado(b.id, "11966665555", "cel-da-maria") is True
    assert esta_bloqueado(b.id, "11966665555", "outro-cel") is False
    assert esta_bloqueado(b.id, "11966665555", None) is False


def test_bloqueio_nao_vaza_para_outra_barbearia(cenario):
    b, d = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b.id)
    a = _agendamento(b.id, zeca, _cliente(b.id), AGORA + timedelta(days=1), aparelho="cel")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    _cliente(d.id)
    assert esta_bloqueado(d.id, "11977778888", "cel") is False


# ------------------------------------------------------------------ bloquear


def test_bloquear_cancela_so_os_futuros_confirmados_de_qualquer_barbeiro(cenario):
    b = cenario["brutus"]
    zeca, tuca = _barbeiro(b.id, "Zeca"), _barbeiro(b.id, "Tuca")
    maria = _cliente(b.id)
    origem = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    do_colega = _agendamento(b.id, tuca, maria, AGORA + timedelta(days=2))
    passado = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=1))
    ja_cancelado = _agendamento(
        b.id, zeca, maria, AGORA + timedelta(days=3), status="CANCELADO_CLIENTE",
    )

    cancelados = bloquear(b.id, origem.id, None, zeca.id, AGORA)

    assert {str(c[1]) for c in cancelados} == {str(origem.id), str(do_colega.id)}
    assert _status(origem) == "CANCELADO_BARBEIRO"
    assert _status(do_colega) == "CANCELADO_BARBEIRO"
    assert _status(passado) == "CONFIRMADO"
    assert _status(ja_cancelado) == "CANCELADO_CLIENTE"


def test_bloquear_grava_quem_e_quando(cenario):
    from tenant.models import Cliente

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    c = Cliente.objects.using("owner").get(id=maria.id)
    assert c.bloqueado_em is not None
    assert str(c.bloqueado_por_id) == str(zeca.id)


def test_bloquear_de_novo_nao_cancela_nada(cenario):
    """O barbeiro marcou ela pelo painel depois do bloqueio (decisao dele).
    Apertar bloquear de novo nao pode desfazer isso."""
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA - timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)
    pelo_painel = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))

    assert bloquear(b.id, a.id, None, zeca.id, AGORA) == []
    assert _status(pelo_painel) == "CONFIRMADO"


def test_barbeiro_nao_bloqueia_pelo_agendamento_do_colega(cenario):
    b = cenario["brutus"]
    eu, colega = _barbeiro(b.id, "Eu"), _barbeiro(b.id, "Colega")
    a = _agendamento(b.id, colega, _cliente(b.id), AGORA + timedelta(days=1))

    assert bloquear(b.id, a.id, eu.id, eu.id, AGORA) is None
    assert previa(b.id, a.id, eu.id, AGORA) is None
    assert esta_bloqueado(b.id, "11977778888", None) is False


def test_previa_conta_os_horarios_que_seriam_cancelados(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    _agendamento(b.id, zeca, maria, AGORA + timedelta(days=2))
    _agendamento(b.id, zeca, maria, AGORA - timedelta(days=2))

    assert previa(b.id, a.id, None, AGORA) == {
        "clienteId": str(maria.id), "nome": "Maria", "whatsapp": "11977778888",
        "horarios": 2, "bloqueado": False,
    }


# ------------------------------------------------------ listar / desbloquear


def test_listar_traz_os_bloqueados_com_quem_bloqueou(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    _cliente(b.id, whatsapp="11955554444", nome="Livre")
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    lista = listar(b.id)
    assert [(c["id"], c["nome"], c["whatsapp"], c["bloqueadoPor"]) for c in lista] == [
        (str(maria.id), "Maria", "11977778888", "Zeca"),
    ]
    assert lista[0]["bloqueadoEm"] is not None


def test_desbloquear_libera_numero_e_aparelho(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1), aparelho="cel")
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert desbloquear(b.id, maria.id) is True
    assert esta_bloqueado(b.id, "11977778888", None) is False
    assert esta_bloqueado(b.id, "11966665555", "cel") is False
    assert listar(b.id) == []
    # Os horarios cancelados no bloqueio nao voltam.
    assert _status(a) == "CANCELADO_BARBEIRO"


def test_desbloquear_cliente_de_outra_barbearia_nao_acha(cenario):
    b, d = cenario["brutus"], cenario["dontony"]
    zeca = _barbeiro(b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, zeca, maria, AGORA + timedelta(days=1))
    bloquear(b.id, a.id, None, zeca.id, AGORA)

    assert desbloquear(d.id, maria.id) is False
    assert esta_bloqueado(b.id, "11977778888", None) is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_clientes_bloqueados.py`
Expected: FAIL — `ModuleNotFoundError: app.services.clientes_bloqueados`.

- [ ] **Step 3: Implementar**

```python
"""Clientes bloqueados (spec 2026-10-13): a equipe bloqueia quem marca e nao
aparece. O site recusa o numero, e qualquer aparelho que ja' marcou com ele,
sem dizer por que — a frase da recusa manda a pessoa chamar a barbearia.

O aparelho e' CONSULTADO, e nao copiado no bloqueio: assim pega tambem o
celular que marcou com o numero antes de ele ser bloqueado, e desbloquear e'
apagar um campo so'.
"""

from datetime import datetime

from django.utils import timezone

from tenant.models import Agendamento, Cliente
from tenant.rls import com_barbearia


def esta_bloqueado(barbearia_id, whatsapp: str, aparelho: str | None) -> bool:
    with com_barbearia(barbearia_id):
        if Cliente.objects.filter(whatsapp=whatsapp, bloqueado_em__isnull=False).exists():
            return True
        if not aparelho:
            return False
        return Agendamento.objects.filter(
            aparelho=aparelho, cliente__bloqueado_em__isnull=False,
        ).exists()


def _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id):
    """O cliente do agendamento, ou None. Barbeiro comum so' alcanca os
    agendamentos dele — o do colega e' None (a rota responde 404, como o
    cancelar: 403 confirmaria que existe)."""
    a = Agendamento.objects.filter(id=agendamento_id).select_related("cliente").first()
    if a is None:
        return None
    if filtro_barbeiro_id and filtro_barbeiro_id != a.barbeiro_id:
        return None
    return a.cliente


def _futuros(cliente_id, agora: datetime):
    return Agendamento.objects.filter(
        cliente_id=cliente_id, status="CONFIRMADO", inicio__gt=agora,
    )


def previa(barbearia_id, agendamento_id, filtro_barbeiro_id, agora: datetime) -> dict | None:
    """O que a confirmacao do painel mostra antes de bloquear."""
    with com_barbearia(barbearia_id):
        c = _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id)
        if c is None:
            return None
        return {
            "clienteId": str(c.id), "nome": c.nome, "whatsapp": c.whatsapp,
            "horarios": _futuros(c.id, agora).count(),
            "bloqueado": c.bloqueado_em is not None,
        }


def bloquear(barbearia_id, agendamento_id, filtro_barbeiro_id, por_id, agora: datetime):
    """Marca o cliente e cancela os horarios futuros dele, com qualquer
    barbeiro, SEM mensagem (quem chama tambem nao manda). Devolve os
    cancelados `(barbeiro_id, agendamento_id, inicio)` para a rota refazer a
    lista do dia; `[]` se ja' estava bloqueado; None se nao achou.

    Ja' bloqueado nao cancela de novo: o que existe agora foi marcado pelo
    painel depois do bloqueio, e isso foi decisao de alguem da equipe."""
    with com_barbearia(barbearia_id):
        c = _cliente_do_agendamento(agendamento_id, filtro_barbeiro_id)
        if c is None:
            return None
        if c.bloqueado_em is not None:
            return []
        Cliente.objects.filter(id=c.id).update(
            bloqueado_em=timezone.now(), bloqueado_por_id=por_id,
        )
        cancelados = list(_futuros(c.id, agora).values_list("barbeiro_id", "id", "inicio"))
        _futuros(c.id, agora).update(status="CANCELADO_BARBEIRO", cancelado_em=timezone.now())
    return cancelados


def listar(barbearia_id) -> list[dict]:
    with com_barbearia(barbearia_id):
        linhas = list(
            Cliente.objects.filter(bloqueado_em__isnull=False)
            .order_by("-bloqueado_em")
            .values("id", "nome", "whatsapp", "bloqueado_em", "bloqueado_por__nome")
        )
    return [
        {
            "id": str(l["id"]), "nome": l["nome"], "whatsapp": l["whatsapp"],
            "bloqueadoEm": l["bloqueado_em"], "bloqueadoPor": l["bloqueado_por__nome"],
        }
        for l in linhas
    ]


def desbloquear(barbearia_id, cliente_id) -> bool:
    """Os horarios cancelados no bloqueio NAO voltam."""
    with com_barbearia(barbearia_id):
        return bool(
            Cliente.objects.filter(id=cliente_id, bloqueado_em__isnull=False)
            .update(bloqueado_em=None, bloqueado_por=None)
        )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_clientes_bloqueados.py`
Expected: PASS (13).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clientes_bloqueados.py tests/test_clientes_bloqueados.py
git commit -m "bloquear cliente: o servico (bloquear, previa, listar, desbloquear, esta_bloqueado)"
```

### Task 3: A recusa e a marca do aparelho no site

**Files:**
- Modify: `backend/app/services/agendamentos.py` (`marcar()`, ~linha 66, e o `Agendamento.objects.create` dentro dela)
- Modify: `backend/app/api/v1/views/agendamentos.py` (`AgendamentosView.post`)
- Test: `tests/test_bloqueio_no_site.py`

**Interfaces:**
- Consumes: `esta_bloqueado` (Tarefa 2).
- Produces: `marcar(..., aparelho: str | None = None)` grava `Agendamento.aparelho`; `COOKIE_APARELHO = "aparelho"` em `app/api/v1/views/agendamentos.py`.

- [ ] **Step 1: Escrever os testes**

Reaproveita os ajudantes de `tests/test_agendamentos.py` importando-os pelo nome do módulo (`tests/` não é pacote; o pytest põe a pasta no `sys.path`):

```python
from unittest.mock import patch

import pytest

from app.services.clientes_bloqueados import bloquear
from app.services.lista_do_dia import SEM_LISTA
from test_agendamentos import (
    CABECALHO, HOST, _barbeiro, _envios, _proximo_slot_livre, _servico_vinculado,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


@pytest.fixture(autouse=True)
def _sem_lista():
    with patch("app.services.lista_do_dia.avisar_mudanca", return_value=SEM_LISTA):
        yield


def _marcar(client, barbeiro, servico, inicio, whatsapp):
    with _envios() as envios:
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Maria", "whatsapp": whatsapp,
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    return r, envios


def _bloquear_quem_marcou(barbearia, codigo, por):
    from datetime import datetime, timezone

    from tenant.models import Agendamento

    a = Agendamento.objects.using("owner").get(codigo=codigo)
    bloquear(barbearia.id, a.id, None, por.id, datetime.now(timezone.utc))


def test_primeiro_agendamento_ganha_a_marca_do_aparelho(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")

    assert r.status_code == 201
    marca = r.cookies["aparelho"]
    assert marca.value and marca["httponly"] and marca["samesite"] == "Lax"
    assert Agendamento.objects.using("owner").get(codigo=r.json()["codigo"]).aparelho == marca.value


def test_aparelho_que_ja_tem_marca_nao_ganha_outra(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    client.cookies["aparelho"] = "marca-antiga"
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")

    assert r.status_code == 201
    assert "aparelho" not in r.cookies
    assert Agendamento.objects.using("owner").get(codigo=r.json()["codigo"]).aparelho == "marca-antiga"


def test_numero_bloqueado_recebe_o_erro_que_manda_chamar_a_barbearia(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)
    client.cookies.clear()  # outro navegador: so' o numero denuncia

    antes = Agendamento.objects.using("owner").count()
    r, envios = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico, 90), "11977778888")

    assert r.status_code == 422
    assert r.json()["erro"] == (
        "Não foi possível concluir o agendamento. Chama a barbearia: (11) 9 9999-8888"
    )
    assert Agendamento.objects.using("owner").count() == antes
    envios.assert_not_called()


def test_numero_novo_no_mesmo_aparelho_tambem_e_recusado(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)

    # O cookie do primeiro agendamento continua no `client`, como no celular.
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico, 90), "11966665555")
    assert r.status_code == 422


def test_o_painel_continua_marcando_para_o_numero_bloqueado(client, cenario):
    from app.services.sessao import COOKIE_SESSAO, emitir

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)

    client.cookies[COOKIE_SESSAO] = emitir(sub=zeca.id, bid=b.id, papel="BARBEIRO", tv=0)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": zeca.id, "servicoId": servico.id,
                "inicio": _proximo_slot_livre(zeca, servico, 90).isoformat(),
                "nome": "Maria", "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_bloqueio_no_site.py`
Expected: FAIL — sem cookie `aparelho` na resposta, e o número bloqueado recebe 201.

- [ ] **Step 3: `marcar()` aceita e grava o aparelho**

Em `backend/app/services/agendamentos.py`, assinatura:

```python
def marcar(
    *, barbearia_id: str, barbeiro_id: str, servico_id: str, inicio: datetime,
    nome: str, whatsapp: str, agora: datetime, aparelho: str | None = None,
) -> dict:
```

e no `Agendamento.objects.create(...)` de dentro dela, acrescentar `aparelho=aparelho,`.

- [ ] **Step 4: A rota pública recusa e marca**

Em `backend/app/api/v1/views/agendamentos.py`: importar `secrets`, `from django.conf import settings`, `from app.services.clientes_bloqueados import esta_bloqueado`; no topo do módulo:

```python
# A marca do navegador que marca pelo site (spec 2026-10-13). Gravada pelo
# SERVIDOR, e nao por script: o Safari apaga em 7 dias o que o script grava,
# mas nao o cookie que vem na resposta. Host-only, como o de sessao.
COOKIE_APARELHO = "aparelho"
APARELHO_MAX_AGE = 2 * 365 * 24 * 3600
```

Em `post`, logo depois do bloco do `numero_existe` e antes de `agora = ...`:

```python
        # Bloqueado (o numero, ou o aparelho que ja' marcou com um numero
        # bloqueado): a mesma cara das outras recusas, sem dizer por que. A
        # frase manda chamar a barbearia, que e' o que a equipe quer.
        aparelho = request.COOKIES.get(COOKIE_APARELHO) or None
        if esta_bloqueado(self.barbearia_id, whatsapp, aparelho):
            o_lugar = palavras(request.barbearia.tipo)["o_lugar"]
            return Response(
                {
                    "erro": "Não foi possível concluir o agendamento. "
                    f"Chama {o_lugar}: {formatar(request.barbearia.whatsapp_contato)}"
                },
                status=422,
            )
        novo_aparelho = None if aparelho else secrets.token_urlsafe(16)
```

Passar `aparelho=aparelho or novo_aparelho` ao `marcar(...)`, e trocar o `return Response({"codigo": ...}, status=201)` final por:

```python
        resposta = Response({"codigo": criado["codigo"]}, status=201)
        if novo_aparelho:
            resposta.set_cookie(
                COOKIE_APARELHO, novo_aparelho, max_age=APARELHO_MAX_AGE, path="/",
                httponly=True, samesite="Lax", secure=not settings.DEBUG,
            )
        return resposta
```

- [ ] **Step 5: Rodar e ver passar; depois a suíte de agendamentos**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_bloqueio_no_site.py tests/test_agendamentos.py tests/test_agendamentos_painel.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agendamentos.py backend/app/api/v1/views/agendamentos.py tests/test_bloqueio_no_site.py
git commit -m "bloquear cliente: o site recusa numero e aparelho bloqueados, sem dizer por que"
```

### Task 4: As rotas do painel

**Files:**
- Create: `backend/app/api/v1/views/clientes_bloqueados.py`
- Modify: `backend/app/api/v1/router.py` (import + 3 paths perto de `painel/agendamentos/<id:id>/cancelar`)
- Test: `tests/test_clientes_bloqueados_painel.py`

**Interfaces:**
- Consumes: `previa`, `bloquear`, `listar`, `desbloquear` (Tarefa 2).
- Produces (HTTP):
  - `GET  /api/painel/agendamentos/<id>/bloquear-cliente` → 200 `{clienteId, nome, whatsapp, horarios, bloqueado}` | 404
  - `POST /api/painel/agendamentos/<id>/bloquear-cliente` → 200 `{"ok": true, "cancelados": int}` | 404
  - `GET  /api/painel/clientes/bloqueados` → 200 `[{id, nome, whatsapp, bloqueadoEm, bloqueadoPor}]` (dono) | 403
  - `POST /api/painel/clientes/<id>/desbloquear` → 200 `{"ok": true}` | 404 | 403

- [ ] **Step 1: Escrever os testes**

```python
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from test_clientes_bloqueados import _agendamento, _barbeiro, _cliente

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _h():
    return {"host": HOST, **CABECALHO}


def test_previa_e_bloquear_pela_agenda(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)
    maria = _cliente(b.id)
    futuro = datetime.now(timezone.utc) + timedelta(days=1)
    a = _agendamento(b.id, zeca, maria, futuro)

    r = client.get(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())
    assert r.status_code == 200
    assert r.json()["horarios"] == 1 and r.json()["nome"] == "Maria"

    with patch("app.services.lista_do_dia.avisar_mudanca") as avisar, patch(
        "app.services.whatsapp.enviar_ao_cliente"
    ) as ao_cliente:
        r = client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())
    assert r.status_code == 200
    assert r.json() == {"ok": True, "cancelados": 1}
    ao_cliente.assert_not_called()
    args, kwargs = avisar.call_args
    assert str(args[1]) == str(zeca.id)
    assert [str(i) for i, _ in kwargs["cancelados"]] == [str(a.id)]


def test_bloquear_agendamento_do_colega_e_404(client, cenario):
    b = cenario["brutus"]
    eu, colega = _barbeiro(b.id, "Eu"), _barbeiro(b.id, "Colega")
    _logar(client, eu, b.id)
    a = _agendamento(b.id, colega, _cliente(b.id), datetime.now(timezone.utc) + timedelta(days=1))

    assert client.get(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h()).status_code == 404
    assert client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h()).status_code == 404


def test_bloquear_id_inexistente_ou_torto_e_404(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)

    for id_ in (str(uuid.uuid4()), "nao-existe"):
        r = client.post(f"/api/painel/agendamentos/{id_}/bloquear-cliente", headers=_h())
        assert r.status_code == 404


def test_dono_lista_e_desbloqueia(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    _logar(client, dono, b.id)
    maria = _cliente(b.id)
    a = _agendamento(b.id, dono, maria, datetime.now(timezone.utc) + timedelta(days=1))
    with patch("app.services.lista_do_dia.avisar_mudanca"):
        client.post(f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers=_h())

    r = client.get("/api/painel/clientes/bloqueados", headers=_h())
    assert r.status_code == 200
    assert [c["nome"] for c in r.json()] == ["Maria"]

    r = client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h())
    assert r.status_code == 200
    assert client.get("/api/painel/clientes/bloqueados", headers=_h()).json() == []

    r = client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h())
    assert r.status_code == 404


def test_barbeiro_comum_nao_lista_nem_desbloqueia(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    _logar(client, zeca, b.id)
    maria = _cliente(b.id)

    r = client.get("/api/painel/clientes/bloqueados", headers=_h())
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono vê os clientes bloqueados."
    assert client.post(f"/api/painel/clientes/{maria.id}/desbloquear", headers=_h()).status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_clientes_bloqueados_painel.py`
Expected: FAIL — 404 em todas as rotas (não existem).

- [ ] **Step 3: As views**

```python
from collections import defaultdict
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeDono, ExigeSessao
from app.services import lista_do_dia
from app.services.autorizacao import filtro_do_barbeiro
from app.services.clientes_bloqueados import bloquear, desbloquear, listar, previa


class BloquearClienteView(ExigeSessao, APIView):
    """GET/POST /api/painel/agendamentos/<id>/bloquear-cliente — a partir de
    um horario da agenda, como o cancelar. Qualquer um da equipe; o barbeiro
    so' alcanca os horarios dele (o do colega e' 404)."""

    def get(self, request, id):
        r = previa(
            self.barbearia_id, id, filtro_do_barbeiro(self.sessao).get("barbeiro_id"),
            datetime.now(timezone.utc),
        )
        return Response(r) if r is not None else Response(NAO_ENCONTRADO, status=404)

    def post(self, request, id):
        agora = datetime.now(timezone.utc)
        cancelados = bloquear(
            self.barbearia_id, id, filtro_do_barbeiro(self.sessao).get("barbeiro_id"),
            self.sessao["sub"], agora,
        )
        if cancelados is None:
            return Response(NAO_ENCONTRADO, status=404)
        # Sem WhatsApp ao cliente (decisao do dono). A lista do dia de cada
        # barbeiro afetado sai refeita, se o cancelado era de hoje.
        por_barbeiro = defaultdict(list)
        for barbeiro_id, agendamento_id, inicio in cancelados:
            por_barbeiro[barbeiro_id].append((agendamento_id, inicio))
        for barbeiro_id, pares in por_barbeiro.items():
            lista_do_dia.avisar_mudanca(self.barbearia_id, barbeiro_id, agora, cancelados=pares)
        return Response({"ok": True, "cancelados": len(cancelados)})


class ClientesBloqueadosView(ExigeDono, APIView):
    """GET /api/painel/clientes/bloqueados"""

    mensagem_papel_insuficiente = "Só o dono vê os clientes bloqueados."

    def get(self, request):
        return Response(listar(self.barbearia_id))


class DesbloquearClienteView(ExigeDono, APIView):
    """POST /api/painel/clientes/<id>/desbloquear"""

    mensagem_papel_insuficiente = "Só o dono vê os clientes bloqueados."

    def post(self, request, id):
        if not desbloquear(self.barbearia_id, id):
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
```

- [ ] **Step 4: As rotas**

Em `router.py`, importar `from .views.clientes_bloqueados import BloquearClienteView, ClientesBloqueadosView, DesbloquearClienteView` e, logo depois do path `painel/agendamentos/<id:id>/cancelar`:

```python
    path(
        "painel/agendamentos/<id:id>/bloquear-cliente",
        BloquearClienteView.as_view(),
        name="painel-agendamentos-bloquear-cliente",
    ),
    path(
        "painel/clientes/bloqueados",
        ClientesBloqueadosView.as_view(),
        name="painel-clientes-bloqueados",
    ),
    path(
        "painel/clientes/<id:id>/desbloquear",
        DesbloquearClienteView.as_view(),
        name="painel-clientes-desbloquear",
    ),
```

(O conversor `id` já trata id torto — o teste "nao-existe" da Tarefa 4 confere que vira 404 e não 500; se o conversor deixar passar, o `filter(id=...)` com texto não-UUID levanta `ValidationError`: nesse caso, converter com `tenant.identidade.como_uuid` no começo de cada método e responder 404 para `None`.)

- [ ] **Step 5: Rodar e ver passar; depois a suíte inteira**

Run: `docker exec Marcai-back-api python -m pytest -q -p no:cacheprovider tests/test_clientes_bloqueados_painel.py` e depois sem alvo.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/views/clientes_bloqueados.py backend/app/api/v1/router.py tests/test_clientes_bloqueados_painel.py
git commit -m "bloquear cliente: rotas do painel (previa, bloquear, listar, desbloquear)"
```

### Task 5: Front — bloquear na Agenda

Repo: `Marcai-front`, branch `bloquear-cliente` (`git switch -c bloquear-cliente --no-track origin/main`).

**Files:**
- Modify: `src/lib/api/painelAPI.ts` (tipos + `clientesApi`), `src/lib/api/index.ts` (reexportar)
- Create: `src/lib/bloqueio.ts`
- Modify: `src/components/painel/AgendaDoDia.tsx` (função `bloquear` perto de `cancelar`, ~linha 103; botão perto do "cancelar", ~linha 229)
- Test: `tests/bloqueio.test.ts`

**Interfaces:**
- Produces: `type PreviaDoBloqueio = { clienteId: string; nome: string; whatsapp: string; horarios: number; bloqueado: boolean }`; `type ClienteBloqueado = { id: string; nome: string; whatsapp: string; bloqueadoEm: string; bloqueadoPor: string | null }`; `clientesApi.previa(agendamentoId)`, `clientesApi.bloquear(agendamentoId)`, `clientesApi.bloqueados(signal?)`, `clientesApi.desbloquear(clienteId)`; `textoDaConfirmacao(p: PreviaDoBloqueio): string`.

- [ ] **Step 1: Teste do texto da confirmação**

```ts
import { describe, it, expect } from 'vitest';
import { textoDaConfirmacao } from '@/lib/bloqueio';

const base = { clienteId: 'c', nome: 'Maria', whatsapp: '83982217869', bloqueado: false };

describe('textoDaConfirmacao', () => {
  it('avisa quantos horarios vao ser cancelados', () => {
    expect(textoDaConfirmacao({ ...base, horarios: 3 })).toBe(
      'Bloquear Maria ((83) 9 8221-7869)? Ela não vai conseguir marcar pelo site, '
      + 'e os 3 horários que ela tem marcados vão ser cancelados sem aviso.',
    );
  });

  it('um horario so, no singular', () => {
    expect(textoDaConfirmacao({ ...base, horarios: 1 })).toContain(
      'e o horário que ela tem marcado vai ser cancelado sem aviso.',
    );
  });

  it('sem horario marcado, a segunda metade some', () => {
    expect(textoDaConfirmacao({ ...base, horarios: 0 })).toBe(
      'Bloquear Maria ((83) 9 8221-7869)? Ela não vai conseguir marcar pelo site.',
    );
  });
});
```

Conferir antes que `formatar` de `@/lib/telefone` devolve `(83) 9 8221-7869` para `83982217869` (`tests/telefone.test.ts`); se o formato for outro, ajustar a expectativa ao formato real — o teste é do texto, não do telefone.

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker exec Marcai-front-app sh -c 'cd /app && npx vitest run tests/bloqueio.test.ts'`
Expected: FAIL — módulo `@/lib/bloqueio` não existe.

- [ ] **Step 3: `src/lib/bloqueio.ts`**

```ts
import type { PreviaDoBloqueio } from '@/lib/api';
import { formatar } from '@/lib/telefone';

/// A confirmação antes de bloquear (spec 2026-10-13). Diz o que vai
/// acontecer com os horários dela, porque o cancelamento é sem aviso e não
/// volta ao desbloquear.
export function textoDaConfirmacao(p: PreviaDoBloqueio): string {
  const quem = `Bloquear ${p.nome} (${formatar(p.whatsapp)})? Ela não vai conseguir marcar pelo site`;
  if (p.horarios === 0) return `${quem}.`;
  if (p.horarios === 1) {
    return `${quem}, e o horário que ela tem marcado vai ser cancelado sem aviso.`;
  }
  return `${quem}, e os ${p.horarios} horários que ela tem marcados vão ser cancelados sem aviso.`;
}
```

- [ ] **Step 4: Tipos e `clientesApi` em `painelAPI.ts`**

```ts
/// Bloquear cliente (spec 2026-10-13). A prévia é o que a confirmação mostra.
export type PreviaDoBloqueio = {
  clienteId: string; nome: string; whatsapp: string; horarios: number; bloqueado: boolean;
};

export type ClienteBloqueado = {
  id: string; nome: string; whatsapp: string; bloqueadoEm: string; bloqueadoPor: string | null;
};

export const clientesApi = {
  previa: (agendamentoId: string) =>
    pedir<PreviaDoBloqueio>(`/painel/agendamentos/${agendamentoId}/bloquear-cliente`, {
      loginEm: LOGIN_DO_PAINEL,
    }),
  bloquear: (agendamentoId: string) =>
    pedir<{ ok: true; cancelados: number }>(
      `/painel/agendamentos/${agendamentoId}/bloquear-cliente`, { metodo: 'POST' },
    ),
  bloqueados: (signal?: AbortSignal) =>
    pedir<ClienteBloqueado[]>('/painel/clientes/bloqueados', { signal, loginEm: LOGIN_DO_PAINEL }),
  desbloquear: (clienteId: string) =>
    pedir<{ ok: true }>(`/painel/clientes/${clienteId}/desbloquear`, { metodo: 'POST' }),
};
```

E em `src/lib/api/index.ts`, acrescentar `clientesApi` aos valores e `PreviaDoBloqueio, ClienteBloqueado` aos tipos reexportados de `./painelAPI`, no mesmo estilo das linhas vizinhas.

- [ ] **Step 5: Botão na Agenda**

Em `AgendaDoDia.tsx`, importar `clientesApi` (de `@/lib/api`) e `textoDaConfirmacao` (de `@/lib/bloqueio`); ao lado de `cancelar`:

```tsx
  async function bloquear(item: ItemDaAgenda) {
    const previa = await clientesApi.previa(item.id);
    if (previa.bloqueado) {
      alert(`${previa.nome} já está bloqueada.`);
      return;
    }
    if (!confirm(textoDaConfirmacao(previa))) return;
    await clientesApi.bloquear(item.id);
    void carregar(dia);
  }
```

e, depois do botão "cancelar":

```tsx
                  <span aria-hidden className="text-lbl">·</span>
                  <button onClick={() => bloquear(i)} className="px-1.5 py-1 hover:text-acento">
                    bloquear
                  </button>
```

- [ ] **Step 6: Testes, tipos, commit**

Run: `docker exec Marcai-front-app sh -c 'cd /app && npx vitest run tests/bloqueio.test.ts && npx tsc --noEmit'`
Expected: PASS, tsc sem erro.

```bash
git add src/lib/bloqueio.ts src/lib/api/painelAPI.ts src/lib/api/index.ts src/components/painel/AgendaDoDia.tsx tests/bloqueio.test.ts
git commit -m "bloquear cliente: o botao na agenda, com a confirmacao do que vai ser cancelado"
```

### Task 6: Front — clientes bloqueados na Equipe

**Files:**
- Create: `src/components/painel/ClientesBloqueados.tsx`
- Modify: `src/app/painel/equipe/page.tsx` (ramo do dono, depois do `FormBarbeiro`)

**Interfaces:**
- Consumes: `clientesApi.bloqueados`, `clientesApi.desbloquear`, `ClienteBloqueado` (Tarefa 5).

- [ ] **Step 1: O componente**

```tsx
'use client';
import { useCallback, useEffect, useState } from 'react';
import { Cartao, BotaoVazado, Texto } from '@/components/painel/pecas';
import { formatar } from '@/lib/telefone';
import { clientesApi, mensagemDoErro, type ClienteBloqueado } from '@/lib/api';

/// Quem a equipe bloqueou (spec 2026-10-13). Só o dono vê esta lista e só
/// ele desbloqueia; bloquear é pela Agenda. Desbloquear libera o número e o
/// aparelho na hora, mas os horários cancelados no bloqueio não voltam.
const quando = (iso: string) => new Date(iso).toLocaleDateString('pt-BR');

export function ClientesBloqueados() {
  const [lista, setLista] = useState<ClienteBloqueado[] | null>(null);
  const [erro, setErro] = useState('');

  const carregar = useCallback((signal?: AbortSignal) =>
    clientesApi.bloqueados(signal)
      .then((l) => { setLista(l); setErro(''); })
      .catch((e) => {
        if ((e as Error)?.name === 'AbortError') return;
        setLista([]);
        setErro(mensagemDoErro(e));
      }), []);

  useEffect(() => {
    const ctrl = new AbortController();
    void carregar(ctrl.signal);
    return () => ctrl.abort();
  }, [carregar]);

  async function desbloquear(c: ClienteBloqueado) {
    if (!confirm(`Desbloquear ${c.nome}? Ela volta a conseguir marcar pelo site.`)) return;
    try {
      await clientesApi.desbloquear(c.id);
      await carregar();
    } catch (e) {
      setErro(mensagemDoErro(e));
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-[17px] font-bold text-tinta">Clientes bloqueados</h2>
      {lista === null && <Texto>carregando…</Texto>}
      {erro && <Texto className="text-acento">{erro}</Texto>}
      {lista?.length === 0 && !erro && (
        <Texto>Ninguém bloqueado. Para bloquear, use o botão na Agenda.</Texto>
      )}
      {lista?.map((c) => (
        <Cartao key={c.id}>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-[15px] font-bold text-tinta">{c.nome}</div>
              <div className="text-[12.5px] text-sub">
                {formatar(c.whatsapp)} · {c.bloqueadoPor ? `por ${c.bloqueadoPor}, ` : ''}
                em {quando(c.bloqueadoEm)}
              </div>
            </div>
            <BotaoVazado onClick={() => desbloquear(c)}>desbloquear</BotaoVazado>
          </div>
        </Cartao>
      ))}
    </section>
  );
}
```

Antes de escrever: conferir em `src/components/painel/pecas.tsx` que `Cartao`, `BotaoVazado` e `Texto` existem com essas props (`Texto` aceita `className`; `BotaoVazado` aceita `onClick`). Se algum não aceitar, usar o que `Equipe.tsx` usa para o mesmo papel.

- [ ] **Step 2: Na tela Equipe**

Em `src/app/painel/equipe/page.tsx`, importar `ClientesBloqueados` e, no ramo do dono, depois de `<FormBarbeiro ... />`:

```tsx
              <Fio className="my-1" />
              <ClientesBloqueados />
```

- [ ] **Step 3: Tipos, testes, olhar a tela**

Run: `docker exec Marcai-front-app sh -c 'cd /app && npx tsc --noEmit && npm test'`
Expected: PASS. Depois abrir `znt.localhost:3000/painel/equipe` e `/painel` (Agenda) no dev: bloquear um horário de teste, conferir a confirmação, a lista na Equipe e o desbloquear; tentar marcar pelo site com o número bloqueado e ver a frase.

- [ ] **Step 4: Commit**

```bash
git add src/components/painel/ClientesBloqueados.tsx src/app/painel/equipe/page.tsx
git commit -m "bloquear cliente: a lista de bloqueados na equipe, com desbloquear"
```

### Task 7: PRs

- [ ] Ajustar a seção 3 da spec para as rotas reais (`/painel/agendamentos/<id>/bloquear-cliente` no lugar de `/painel/clientes/bloquear`), commit.
- [ ] `git push -u origin bloquear-cliente` nos dois repos; abrir `Marcai-back` PR e `Marcai-front` PR (o front depende do back; sobem no mesmo Deploy; o back tem migration 0012 — lembrar do [dev ao vivo]: `migrate` no contêiner depois do pull).
- [ ] Esperar o CI verde dos dois.
