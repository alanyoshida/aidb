"""Unitários do broker: extração/validação do token e contexto (tasks 3.2/3.3)."""

import pytest

from appaiforge import auth, inference_token
from appaiforge.broker import (
    bearer_token,
    destination_allowed,
    outbound_headers,
    system_id_from_token,
    validate_token,
)
from appaiforge.db import session_scope
from sqlalchemy import select

from appaiforge.models import AgentRun, ChatSession, RunStatus, TokenUsage, UserType
from appaiforge.services.systems import (
    NotPermitted,
    create_system,
    inference_context,
    revoke_session_inference,
)
from appaiforge.services.inference_usage import record_usage


@pytest.fixture()
def owner_system(clean_db):
    editor = auth.create_user("broker@sys.local", "pw", UserType.editor.value)
    return editor, create_system(editor, "Broker", "broker-sys")


def test_bearer_token_extrai():
    assert bearer_token("Bearer abc.def") == "abc.def"
    assert bearer_token("bearer abc.def") == "abc.def"
    assert bearer_token(None) is None
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer") is None
    assert bearer_token("Bearer   ") is None


def test_system_id_from_token():
    assert system_id_from_token("sys123.abc") == "sys123"
    assert system_id_from_token("sem-ponto") is None
    assert system_id_from_token(None) is None
    assert system_id_from_token(".abc") is None


def test_validate_token_aceita_versao_vigente_e_recusa_revogado():
    token = inference_token.emit("sys123", 1)
    assert validate_token(token, 1) == "sys123"
    # versão anterior = revogado
    assert validate_token(token, 2) is None
    # adulterado / ausente
    assert validate_token("sys123.adulterado", 1) is None
    assert validate_token(None, 1) is None


def test_inference_context_sem_execucao_ativa(owner_system):
    _, system = owner_system
    ctx = inference_context(system.id)
    assert ctx is not None
    assert ctx["system_id"] == system.id
    assert ctx["version"] == system.inference_token_version
    assert ctx["provider"] == system.provider
    assert ctx["run_id"] is None
    assert ctx["chat_session_id"] is None


def test_inference_context_com_execucao_ativa(owner_system):
    editor, system = owner_system
    with session_scope() as s:
        run = AgentRun(
            system_id=system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="oi",
        )
        s.add(run)
        s.flush()
        run_id = run.id
    ctx = inference_context(system.id)
    assert ctx is not None
    assert ctx["run_id"] == run_id


def test_inference_context_sistema_inexistente():
    assert inference_context("nao-existe") is None


def test_inference_context_sessao_revogada(owner_system):
    editor, system = owner_system
    with session_scope() as s:
        chat = ChatSession(system_id=system.id, user_id=editor.id, inference_revoked=True)
        s.add(chat)
        s.flush()
        run = AgentRun(
            system_id=system.id, user_id=editor.id, user_email=editor.email,
            chat_session_id=chat.id, status=RunStatus.running, prompt="oi",
        )
        s.add(run)
        s.flush()
    ctx = inference_context(system.id)
    assert ctx is not None
    assert ctx["session_revoked"] is True


def test_outbound_headers_descarta_credencial_do_cliente():
    out = outbound_headers(
        {"Authorization": "Bearer sys.token", "x-api-key": "client", "Content-Type": "application/json"},
        "sk-litellm",
    )
    assert out["Authorization"] == "Bearer sk-litellm"
    assert out["Content-Type"] == "application/json"
    assert "x-api-key" not in out


def test_destination_allowed_respeita_allowlist():
    assert destination_allowed("http://litellm:4000/v1/responses", "litellm,localhost")
    assert destination_allowed("http://localhost:4000/v1", "litellm,localhost")
    assert not destination_allowed("http://evil.example:4000/v1", "litellm,localhost")


@pytest.mark.asyncio
async def test_forward_repassa_chunks_incrementalmente(monkeypatch):
    import asyncio
    import time

    from starlette.requests import Request

    from appaiforge import broker_app

    times: list[float] = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        async def aiter_raw(self):
            for chunk in (b"data: a\n\n", b"data: b\n\n", b"data: c\n\n"):
                await asyncio.sleep(0.05)
                times.append(time.monotonic())
                yield chunk

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, *args, **kwargs):
            return object()

        async def send(self, request, stream=True):
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(broker_app.httpx, "AsyncClient", FakeClient)

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(
        {"type": "http", "method": "POST", "headers": [], "path": "/v1/x", "query_string": b""},
        receive,
    )
    response = await broker_app._forward(request, "v1/x", {})
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    assert chunks == [b"data: a\n\n", b"data: b\n\n", b"data: c\n\n"]
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    assert all(gap >= 0.04 for gap in gaps)


@pytest.mark.asyncio
async def test_cancel_inflight_encerra_so_a_run_alvo():
    from appaiforge import broker_app

    class FakeResponse:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    alvo = FakeResponse()
    outra = FakeResponse()
    await broker_app._register_inflight("run-alvo", alvo)
    await broker_app._register_inflight("run-outra", outra)

    assert await broker_app._cancel_inflight("run-alvo") == 1
    assert alvo.closed is True
    assert outra.closed is False

    assert await broker_app._cancel_inflight("run-alvo") == 0
    await broker_app._cancel_inflight("run-outra")
    assert outra.closed is True


def test_revoke_session_inference_e_seletiva(owner_system):
    editor, system = owner_system
    with session_scope() as s:
        a = ChatSession(system_id=system.id, user_id=editor.id)
        b = ChatSession(system_id=system.id, user_id=editor.id)
        s.add_all([a, b])
        s.flush()
        id_a, id_b = a.id, b.id
    revoke_session_inference(id_a, editor)
    with session_scope() as s:
        assert s.get(ChatSession, id_a).inference_revoked is True
        assert s.get(ChatSession, id_b).inference_revoked is False


def test_revoke_session_inference_sem_permissao(owner_system):
    editor, system = owner_system
    other = auth.create_user("other-session@sys.local", "pw", UserType.editor.value)
    with session_scope() as s:
        cs = ChatSession(system_id=system.id, user_id=editor.id)
        s.add(cs)
        s.flush()
        cid = cs.id
    with pytest.raises(NotPermitted):
        revoke_session_inference(cid, other)


def test_record_usage_idempotente(owner_system):
    editor, system = owner_system
    with session_scope() as s:
        run = AgentRun(
            system_id=system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="oi",
        )
        s.add(run)
        s.flush()
        run_id = run.id
    payload = {
        "id": "evt-1",
        "metadata": {"system_id": system.id, "run_id": run_id},
        "model": "gpt-4o",
        "custom_llm_provider": "openai",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "response_cost": 0.002,
    }
    assert record_usage(payload) is True
    assert record_usage(payload) is False  # mesmo evento não duplica
    with session_scope() as s:
        rows = s.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars().all()
        assert len(rows) == 1
        assert rows[0].input_tokens == 10 and rows[0].output_tokens == 5
        assert rows[0].cost == pytest.approx(0.002)
    assert record_usage(dict(payload, id="evt-2")) is True


def test_record_usage_sem_metadados_nao_registra():
    assert record_usage({"id": "x", "usage": {}}) is False
