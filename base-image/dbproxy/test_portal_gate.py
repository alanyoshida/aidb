"""Unitários do cliente HTTP do gate (task 2.3) — sem rede real: usa
httpx.MockTransport para simular o portal (padrão da própria lib, não um
servidor fake nosso como nos outros arquivos de teste)."""

import asyncio
import json

import httpx
import pytest

import portal_gate
from portal_gate import PortalUnavailable, audit_shadow, request_and_wait, request_approval, wait_decision


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_request_approval_devolve_id_e_manda_o_token(monkeypatch):
    monkeypatch.setattr(portal_gate, "SERVICE_TOKEN", "segredo")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "req-1", "status": "pendente"})

    async def go():
        async with _client(handler) as client:
            return await request_approval(
                client, "sys-1", "DELETE FROM t", origin="agente", reason="sem WHERE"
            )

    req_id = _run(go())
    assert req_id == "req-1"
    assert seen["headers"]["x-aidb-dbgate-token"] == "segredo"
    assert seen["body"]["system_id"] == "sys-1"
    assert seen["body"]["sql"] == "DELETE FROM t"


def test_request_approval_portal_recusa_levanta_portal_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "não autorizado"})

    async def go():
        async with _client(handler) as client:
            await request_approval(client, "sys-1", "DELETE FROM t", origin="agente")

    with pytest.raises(PortalUnavailable):
        _run(go())


def test_request_approval_erro_de_rede_levanta_portal_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusado")

    async def go():
        async with _client(handler) as client:
            await request_approval(client, "sys-1", "DELETE FROM t", origin="agente")

    with pytest.raises(PortalUnavailable):
        _run(go())


def test_wait_decision_poll_ate_sair_de_pendente():
    statuses = iter(["pendente", "pendente", "aprovada"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "req-1", "status": next(statuses)})

    async def go():
        async with _client(handler) as client:
            return await wait_decision(client, "req-1", poll_interval=0.001)

    assert _run(go()) == "aprovada"


def test_wait_decision_sobrevive_falha_intermitente_de_rede():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise httpx.ConnectError("portal reiniciando")
        return httpx.Response(200, json={"id": "req-1", "status": "recusada"})

    async def go():
        async with _client(handler) as client:
            return await wait_decision(client, "req-1", poll_interval=0.001)

    assert _run(go()) == "recusada"
    assert attempts["n"] == 3


def test_wait_decision_404_levanta_portal_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "pedido não encontrado"})

    async def go():
        async with _client(handler) as client:
            await wait_decision(client, "req-inexistente", poll_interval=0.001)

    with pytest.raises(PortalUnavailable):
        _run(go())


# ---------- teto de espera do proxy (task 4.3) — rede fora do ar pra sempre não deve travar ----------

def test_wait_decision_desiste_apos_teto_com_rede_sempre_fora():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("portal inalcançável")

    async def go():
        async with _client(handler) as client:
            await wait_decision(client, "req-1", poll_interval=0.01, max_wait_seconds=0.05)

    with pytest.raises(PortalUnavailable):
        _run(go())  # não deve travar — o teste em si é a prova de que não hangeia


def test_wait_decision_desiste_apos_teto_mesmo_sempre_pendente():
    """Defesa em profundidade: mesmo se o pedido nunca saísse de "pendente"
    (bug no portal, relógio desalinhado), o teto do proxy ainda desiste."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "req-1", "status": "pendente"})

    async def go():
        async with _client(handler) as client:
            await wait_decision(client, "req-1", poll_interval=0.01, max_wait_seconds=0.05)

    with pytest.raises(PortalUnavailable):
        _run(go())


def test_decide_confirmable_desiste_apos_teto_e_recusa_com_seguranca(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"id": "req-timeout", "status": "pendente"})
        raise httpx.ConnectError("portal inalcançável")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=httpx.MockTransport(handler)))

    async def go():
        ctx = portal_gate.GateContext(system_id="sys-1")
        logged = []
        status = await portal_gate.decide_confirmable(
            ctx, "DELETE FROM t", "sem WHERE", log=lambda *a: logged.append(a), max_wait_seconds=0.05
        )
        return status, logged

    status, logged = _run(go())
    assert status == "recusada"
    assert logged  # o proxy registrou que recusou por segurança, não silenciosamente


def test_request_and_wait_integra_create_e_poll(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"id": "req-9", "status": "pendente"})
        return httpx.Response(200, json={"id": "req-9", "status": "expirada"})

    # request_and_wait cria seu próprio AsyncClient — substitui pelo MockTransport
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=httpx.MockTransport(handler)))

    async def go():
        return await request_and_wait("sys-1", "DELETE FROM t", origin="agente", poll_interval=0.001)

    assert _run(go()) == "expirada"


# ---------- auditoria em modo sombra (task 6.1) ----------

def test_audit_shadow_manda_o_payload_certo(monkeypatch):
    monkeypatch.setattr(portal_gate, "SERVICE_TOKEN", "segredo")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["token"] = request.headers.get("x-aidb-dbgate-token")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"classification": "confirmavel"})

    async def go():
        ctx = portal_gate.GateContext(system_id="sys-1", origin="agente", connection_name="vendas")
        await audit_shadow(ctx, "DELETE FROM t", log=lambda *a: None)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=httpx.MockTransport(handler)))
    _run(go())

    assert seen["path"] == "/internal/db-gate/audit"
    assert seen["token"] == "segredo"
    assert seen["body"] == {
        "system_id": "sys-1", "sql": "DELETE FROM t", "origin": "agente",
        "connection_name": "vendas", "enforced": False,
    }


def test_audit_shadow_nunca_levanta_mesmo_com_portal_fora_do_ar(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("portal inalcançável")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=httpx.MockTransport(handler)))

    logged = []

    async def go():
        ctx = portal_gate.GateContext(system_id="sys-1")
        await audit_shadow(ctx, "DELETE FROM t", log=lambda *a: logged.append(a))

    _run(go())  # não deve levantar — sombra nunca impacta o cliente
    assert logged  # mas registra que a auditoria falhou


def test_audit_shadow_resposta_de_erro_do_portal_so_loga(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "não autorizado"})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(transport=httpx.MockTransport(handler)))

    logged = []

    async def go():
        ctx = portal_gate.GateContext(system_id="sys-1")
        await audit_shadow(ctx, "DELETE FROM t", log=lambda *a: logged.append(a))

    _run(go())
    assert logged
