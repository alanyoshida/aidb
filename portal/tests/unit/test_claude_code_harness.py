"""Unitários do ClaudeCodeHarness: normalização contra um shim HTTP/SSE
falso. Eventos usados nos testes vêm do shape real observado no spike
(tasks.md, task 1.1 — change add-claude-code-agent-profile), não
inventados."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from appaiforge.harness.claude_code import ClaudeCodeHarness

SESSION = "ses_test123"


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


@pytest.fixture()
def fake_shim():
    """Servidor com os endpoints mínimos do shim (shim.py)."""
    state = {"events": [], "aborted": False}

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload, code=200):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            if self.path == "/session":
                self._json({"id": SESSION})
            elif self.path == f"/session/{SESSION}/prompt":
                self._json({"accepted": True}, 202)
            elif self.path == f"/session/{SESSION}/abort":
                state["aborted"] = True
                self._json({"aborted": True})
            else:
                self._json({"error": "not found"}, 404)

        def do_GET(self):
            if self.path == "/event":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(_sse(state["events"]))
                return
            self._json({"error": "not found"}, 404)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["base"] = f"http://127.0.0.1:{server.server_port}"
    state["server"] = server
    yield state
    server.shutdown()


def _assistant(content):
    return {"type": "assistant", "session_id": SESSION, "message": {"content": content}}


def _user(content, tool_use_result=None):
    evt = {"type": "user", "session_id": SESSION, "message": {"content": content}}
    if tool_use_result is not None:
        evt["tool_use_result"] = tool_use_result
    return evt


def _result(**extra):
    base = {"type": "result", "session_id": SESSION, "subtype": "success", "is_error": False}
    base.update(extra)
    return base


def _run(harness, system, prompt="faça"):
    out: list = []
    harness.run(system, SESSION, prompt, out.append)
    return out


def test_cria_sessao(fake_shim):
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    assert harness.create_session({"slug": "erp"}) == SESSION


def test_fluxo_completo_com_tool_use_e_tool_result(fake_shim):
    fake_shim["events"] = [
        _assistant([{"type": "text", "text": "Vou rodar um comando."}]),
        _assistant([{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest"}}]),
        _user([{"type": "tool_result", "tool_use_id": "toolu_1", "content": "1 passed", "is_error": False}]),
        _assistant([{"type": "text", "text": "Testes passaram."}]),
        _result(usage={"input_tokens": 100, "output_tokens": 50}, result="Testes passaram."),
    ]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp", "model": "claude-opus-5-5"})
    kinds = [e.kind for e in events]
    assert kinds[0] == "run_started"
    assert "message" in kinds and "command_run" in kinds and "usage" in kinds
    assert kinds[-1] == "run_finished"

    running = next(e for e in events if e.kind == "command_run" and e.meta["status"] == "running")
    assert running.meta["command"] == "pytest"
    completed = next(e for e in events if e.kind == "command_run" and e.meta["status"] == "completed")
    assert completed.text == "1 passed"
    assert completed.meta["call_id"] == "toolu_1"

    usage = next(e for e in events if e.kind == "usage")
    assert usage.meta["input_tokens"] == 100
    assert usage.meta["output_tokens"] == 50
    assert usage.meta["model"] == "claude-opus-5-5"
    assert usage.meta["provider"] == "anthropic"


def test_tool_use_edit_mapeia_para_file_edited(fake_shim):
    fake_shim["events"] = [
        _assistant([{"type": "tool_use", "id": "toolu_2", "name": "Edit", "input": {"file_path": "/workspace/app.py"}}]),
        _user([{"type": "tool_result", "tool_use_id": "toolu_2", "content": "ok", "is_error": False}]),
        _result(),
    ]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    edited = [e for e in events if e.kind == "file_edited"]
    assert len(edited) == 2
    assert edited[0].meta["file"] == "/workspace/app.py"
    assert edited[1].meta["status"] == "completed"


def test_tool_desconhecida_mapeia_para_tool_output(fake_shim):
    """Ferramenta MCP (ex.: mcp__gated-mcp__read_query, D6) não tem kind
    próprio - cai no genérico, igual ao opencode faz com ferramentas que
    não são edit/write/bash."""
    fake_shim["events"] = [
        _assistant([{"type": "tool_use", "id": "toolu_3", "name": "mcp__gated-mcp__read_query", "input": {"sql": "select 1"}}]),
        _user([{"type": "tool_result", "tool_use_id": "toolu_3", "content": "[{\"1\":1}]", "is_error": False}]),
        _result(),
    ]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    assert any(e.kind == "tool_output" for e in events)


def test_tool_result_com_erro_marca_meta(fake_shim):
    fake_shim["events"] = [
        _assistant([{"type": "tool_use", "id": "toolu_4", "name": "Bash", "input": {"command": "false"}}]),
        _user([{"type": "tool_result", "tool_use_id": "toolu_4", "content": "comando falhou", "is_error": True}]),
        _result(),
    ]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    completed = next(e for e in events if e.kind == "command_run" and e.meta["status"] == "completed")
    assert completed.meta["is_error"] is True


def test_eventos_de_outra_sessao_sao_ignorados(fake_shim):
    outra = dict(_assistant([{"type": "text", "text": "não é meu"}]))
    outra["session_id"] = "ses_outra"
    fake_shim["events"] = [outra, _result()]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    assert [e.kind for e in events] == ["run_started", "run_finished"]


def test_abort_leva_a_run_interrupted(fake_shim):
    fake_shim["events"] = [_result(subtype="aborted", is_error=True)]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    harness.interrupt({"slug": "erp"}, SESSION)
    events = _run(harness, {"slug": "erp"})
    assert events[-1].kind == "run_interrupted"
    assert fake_shim["aborted"]


def test_result_com_erro_vira_run_error(fake_shim):
    fake_shim["events"] = [_result(subtype="error_during_execution", is_error=True, result="falhou")]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    assert events[-1].kind == "run_error"
    assert events[-1].text == "falhou"


def test_usage_sem_tokens_nao_emite_evento(fake_shim):
    fake_shim["events"] = [_result(usage={})]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    assert all(e.kind != "usage" for e in events)
    assert events[-1].kind == "run_finished"


def test_eventos_system_de_housekeeping_sao_ignorados(fake_shim):
    """system/init, hook_started/hook_response, api_retry etc. (achados
    reais do spike) não viram RunEvent nenhum."""
    fake_shim["events"] = [
        {"type": "system", "subtype": "init", "session_id": SESSION, "tools": []},
        {"type": "system", "subtype": "api_retry", "session_id": SESSION, "attempt": 1},
        _result(),
    ]
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    events = _run(harness, {"slug": "erp"})
    assert [e.kind for e in events] == ["run_started", "run_finished"]


def test_reply_gate_e_reply_question_sao_no_op(fake_shim):
    """D do design: sem equivalente no v1 - não lança e não faz requisição
    HTTP nenhuma (o fake_shim nem registra rota pra isso; se tentasse, a
    chamada estourraria 404/conexão, não um retorno silencioso)."""
    harness = ClaudeCodeHarness(lambda sys_: fake_shim["base"])
    system = {"slug": "erp"}
    assert harness.reply_gate(system, SESSION, "req_1", approve=True) is None
    assert harness.reply_gate(system, SESSION, "req_1", approve=False) is None
    assert harness.reply_question(system, SESSION, "req_1", "Sim") is None
    assert harness.reject_question(system, SESSION, "req_1") is None
