"""Unitários do cliente HTTP do gate (task 2.3) — sem rede real: usa
httpx.MockTransport para simular o portal (padrão da própria lib, não um
servidor fake nosso como nos outros arquivos de teste).

`bloqueada`/`confirmável` em modo enforce são recusadas direto pelo proxy,
sem pedir decisão ao portal — o único papel deste cliente agora é a
auditoria (`audit_shadow`)."""

import asyncio
import json

import httpx

import portal_gate
from portal_gate import audit_shadow


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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
