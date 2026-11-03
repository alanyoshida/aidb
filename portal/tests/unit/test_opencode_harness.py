"""Unitários do OpencodeHarness: normalização contra servidor HTTP/SSE falso."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from appaiforge.harness.opencode import OpencodeHarness, opencode_provider

SESSION = "ses_test123"


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


@pytest.fixture()
def fake_opencode():
    """Servidor com endpoints mínimos do opencode serve."""
    state = {"events": [], "aborted": False, "replies": []}

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
            body = self.rfile.read(length)
            if self.path == "/session":
                self._json({"id": SESSION})
            elif self.path == f"/session/{SESSION}/prompt_async":
                self._json({"ok": True})
            elif self.path == f"/session/{SESSION}/abort":
                state["aborted"] = True
                self._json({"ok": True})
            elif "/permissions/" in self.path or ("/permission/" in self.path and self.path.endswith("/reply")):
                state.setdefault("replies", []).append((self.path, body.decode()))
                self._json({"ok": True})
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


def _evt(type_, **props):
    return {"id": "evt_x", "type": type_, "properties": props}


def _run(harness, system, prompt="faça"):
    out: list = []
    harness.run(system, SESSION, prompt, out.append)
    return out


def test_cria_sessao(fake_opencode):
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    assert harness.create_session({"slug": "erp"}).startswith("ses_")


def test_fluxo_completo_normaliza_eventos(fake_opencode):
    fake_opencode["events"] = [
        _evt("message.updated", sessionID=SESSION, info={"role": "assistant", "model": {"providerID": "zhipuai", "modelID": "glm-4.6"}, "tokens": {"input": {"tokens": 100}, "output": {"tokens": 50}}}),
        _evt("message.part.updated", sessionID=SESSION, part={"type": "text", "text": "vou criar o arquivo"}),
        _evt("message.part.updated", sessionID=SESSION, part={"type": "tool", "tool": "edit", "state": {"input": {"filePath": "/workspace/app/main.py"}, "output": "ok"}}),
        _evt("message.part.updated", sessionID=SESSION, part={"type": "tool", "tool": "bash", "state": {"input": {"command": "pytest"}, "output": "1 passed"}}),
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    events = _run(harness, {"slug": "erp"})
    kinds = [e.kind for e in events]
    assert kinds[0] == "run_started"
    assert "usage" in kinds and "message" in kinds and "file_edited" in kinds and "command_run" in kinds
    assert kinds[-1] == "run_finished"
    usage = next(e for e in events if e.kind == "usage")
    assert usage.meta["input_tokens"] == 100 and usage.meta["model"] == "glm-4.6"
    edited = next(e for e in events if e.kind == "file_edited")
    assert edited.meta["file"].endswith("main.py")


def test_eventos_de_outra_sessao_sao_ignorados(fake_opencode):
    fake_opencode["events"] = [
        _evt("message.part.updated", sessionID="ses_outro", part={"type": "text", "text": "não é meu"}),
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    events = _run(harness, {"slug": "erp"})
    assert [e.kind for e in events] == ["run_started", "run_finished"]


def test_abort_leva_a_run_interrupted(fake_opencode):
    fake_opencode["events"] = [
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    harness.interrupt({"slug": "erp"}, SESSION)
    events = _run(harness, {"slug": "erp"})
    assert events[-1].kind == "run_interrupted"
    assert fake_opencode["aborted"]


def test_mapa_de_provedores():
    assert opencode_provider("glm") == ("zhipuai", "ZHIPU_API_KEY")
    assert opencode_provider("anthropic") == ("anthropic", "ANTHROPIC_API_KEY")


def test_usage_em_formato_int_do_provedor(fake_opencode):
    """GLM reporta tokens como inteiros ({input: 5}); o normalizador não pode quebrar."""
    fake_opencode["events"] = [
        _evt("message.updated", sessionID=SESSION, info={"role": "assistant", "model": {"providerID": "zhipuai", "modelID": "glm-4.6"}, "tokens": {"input": 120, "output": 80}}),
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    events = _run(harness, {"slug": "erp"})
    usage = next(e for e in events if e.kind == "usage")
    assert usage.meta["input_tokens"] == 120
    assert usage.meta["output_tokens"] == 80
    assert events[-1].kind == "run_finished"


def test_partes_malformadas_nao_quebram_o_stream(fake_opencode):
    fake_opencode["events"] = [
        _evt("message.updated", sessionID=SESSION, info={"role": "assistant", "model": 0}),
        _evt("session.status", sessionID=SESSION, status=3),
        _evt("session.diff", sessionID=SESSION, diff="lixo"),
        _evt("message.part.updated", sessionID=SESSION, part={"type": "tool", "tool": "bash", "state": "erro"}),
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    events = _run(harness, {"slug": "erp"})
    assert events[-1].kind == "run_finished"


def test_gate_request_normalizado_e_reply(fake_opencode):
    fake_opencode["events"] = [
        _evt("permission.asked", sessionID=SESSION, id="per_123", permission="bash",
             metadata={"command": 'psql "$URL" -c "DELETE FROM clientes"'}),
        _evt("session.status", sessionID=SESSION, status={"type": "idle"}),
    ]
    replies = []

    from http.server import BaseHTTPRequestHandler, HTTPServer as HS2

    class ReplyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            replies.append((self.path, body.decode()))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    harness = OpencodeHarness(lambda sys_: fake_opencode["base"])
    harness.reply_gate({"slug": "erp"}, SESSION, "per_123", approve=False)
    replies = fake_opencode["replies"]
    assert replies and f"/session/{SESSION}/permissions/per_123" in replies[0][0]
    assert '"reject"' in replies[0][1]

    events = _run(harness, {"slug": "erp"})
    gate_events = [e for e in events if e.kind == "gate_request"]
    assert len(gate_events) == 1
    assert gate_events[0].meta["request_id"] == "per_123"
    assert "DELETE FROM clientes" in gate_events[0].text
