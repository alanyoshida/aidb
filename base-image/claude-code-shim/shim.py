"""Shim HTTP de vida longa pro agente claude-code (etapa 7 do roadmap de
confinamento, change `add-claude-code-agent-profile`).

O supervisor (`afsupervisor`) sobe este processo como o `command` do perfil
`claude-code`, do mesmo jeito que hoje sobe `opencode serve` (D1 do design) —
ele nunca sabe que, por baixo, quem responde por prompt é a CLI `claude` em
modo headless, invocada como subprocesso curto por turno (não um servidor).

Endpoints (espelham o uso que `appaiforge/harness/opencode.py` faz de
`opencode serve`, pro dispatch genérico de `HARNESS_IMPLEMENTATIONS` não
precisar saber a diferença):
    POST /session               -> cria sessão lógica, devolve {"id": ...}
    POST /session/{id}/prompt   -> dispara prompt sem bloquear (como o
                                    `prompt_async` do opencode); 404 se a
                                    sessão lógica não existe
    POST /session/{id}/abort    -> mata o subprocesso em andamento
    GET  /event                 -> SSE global; cada linha stdout da CLI
                                    (stream-json) é repassada como veio, só
                                    com "session_id" reescrito pro id lógico
                                    (D2) — `ClaudeCodeHarness._normalize`
                                    interpreta o shape; o shim não interpreta
                                    nada do CONTEÚDO do evento.

Achados do spike real (tasks.md, task 1.1-1.4 — ver FINDINGS.md do spike):
  - cada content block de um turno chega como um evento "assistant" PRÓPRIO
    (não um "assistant" só com vários blocks dentro de "content").
  - "--resume <id>" é puramente client-side: a CLI reenvia, por conta
    própria, o histórico completo salvo em ~/.claude/projects/...; não há
    nada equivalente a sessão server-side do opencode.
  - id de sessão inválido falha com exit!=0 e um evento
    {"type":"result","subtype":"error_during_execution","is_error":true}.
  - "--print --output-format stream-json" exige "--verbose" junto, senão
    erro imediato.
  - credencial via env ANTHROPIC_API_KEY (x-api-key) — não ANTHROPIC_AUTH_TOKEN
    — é o que o broker real já sabe trocar (ver agent_profiles.py).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue

# Precisa bater com PROFILES["claude-code"]["config_path"] em agent_profiles.py
# — o diretório de config é montado só-leitura, fora do workspace (spec
# agent-runtime, "Perfil entregue ao container sem segredo").
SETTINGS_PATH = os.environ.get("CLAUDE_CODE_SETTINGS_PATH", "/claude-code-config/settings.json")
# D6: segundo arquivo no mesmo diretório montado — `write_claude_code_config`
# (task 5.3) só grava isto quando o sistema tem alguma DbConnection; sistemas
# sem conexão nenhuma não têm o arquivo, e build_claude_args não passa
# --mcp-config à toa (confirmado no spike que --strict-mcp-config sem
# nenhum --mcp-config simplesmente desliga toda ferramenta MCP, sem erro).
MCP_CONFIG_PATH = os.environ.get("CLAUDE_CODE_MCP_CONFIG_PATH", "/claude-code-config/mcp-servers.json")
WORKSPACE_DIR = "/workspace"

# Desliga telemetria/auto-update da CLI (D4 do design) em vez de abrir a
# allow-list do proxy HTTPS de saída pros hosts que ela normalmente usa.
_TELEMETRY_OFF_ENV = {
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}


def build_claude_args(
    prompt: str,
    model: str | None,
    resume_cli_session_id: str | None,
    mcp_config_path: str | None = None,
) -> list[str]:
    """Monta os args da CLI pra um turno. Função pura, sem subprocess —
    isolada assim pra poder testar a decisão de incluir ou não `--resume`/
    `--mcp-config` sem precisar mockar subprocess.Popen inteiro."""
    args = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
        "--settings", SETTINGS_PATH,
    ]
    if model:
        args += ["--model", model]
    if resume_cli_session_id:
        args += ["--resume", resume_cli_session_id]
    if mcp_config_path:
        # --strict-mcp-config (D6): só as ferramentas MCP que o perfil entrega
        # por este arquivo — nenhuma outra fonte de MCP do ambiente da CLI.
        args += ["--mcp-config", mcp_config_path, "--strict-mcp-config"]
    return args


def build_claude_env(base_env: dict) -> dict:
    """Env do subprocesso: env do container + telemetria/auto-update desligados."""
    env = dict(base_env)
    env.update(_TELEMETRY_OFF_ENV)
    return env


def parse_event_line(raw_line: str) -> dict | None:
    """Parseia uma linha stdout da CLI (um objeto JSON por linha). Linha
    vazia ou que não parseia como objeto JSON é ignorada (achado real: a CLI
    pode emitir linhas em branco entre eventos)."""
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def translate_event(event: dict, logical_session_id: str) -> dict:
    """Reescreve "session_id" pro id lógico do portal (D2) — sem interpretar
    mais nada do conteúdo; `ClaudeCodeHarness._normalize` interpreta o shape."""
    translated = dict(event)
    if "session_id" in translated:
        translated["session_id"] = logical_session_id
    return translated


class SessionState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cli_session_id: str | None = None
        self.proc: subprocess.Popen | None = None
        self.abort_requested = False


class EventBus:
    """Fan-out simples: cada `GET /event` aberto registra uma Queue própria;
    `publish` empilha o envelope em todas. Mesma forma que o `GET /event`
    global do opencode (harness filtra por sessionID do lado dele)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Queue] = []

    def subscribe(self) -> Queue:
        q: Queue = Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, envelope: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(envelope)


class ShimState:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.sessions_lock = threading.Lock()
        self.bus = EventBus()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self.sessions_lock:
            self.sessions[session_id] = SessionState()
        return session_id

    def get_session(self, session_id: str) -> SessionState | None:
        with self.sessions_lock:
            return self.sessions.get(session_id)


def _drain(stream) -> None:
    """Esvazia stderr pra não travar o pipe do subprocesso; não precisamos
    do conteúdo (a CLI já reporta erro via o evento "result" no stdout)."""
    try:
        for _ in stream:
            pass
    except Exception:
        pass


def run_prompt(state: ShimState, session_id: str, session: SessionState, prompt: str, model: str | None) -> None:
    """Roda um turno completo: spawna a CLI, lê stdout linha a linha,
    republica cada evento traduzido (D2) e garante um evento terminal
    sempre que o processo sair, mesmo sem um "result" explícito da CLI
    (ex.: subprocesso matado por /abort)."""
    with session.lock:
        resume_id = session.cli_session_id
    mcp_config_path = MCP_CONFIG_PATH if os.path.exists(MCP_CONFIG_PATH) else None
    args = build_claude_args(prompt, model, resume_id, mcp_config_path)
    env = build_claude_env(os.environ.copy())

    proc = subprocess.Popen(
        args, cwd=WORKSPACE_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    with session.lock:
        session.proc = proc

    stderr_thread = threading.Thread(target=_drain, args=(proc.stderr,), daemon=True)
    stderr_thread.start()

    saw_result = False
    try:
        for raw_line in proc.stdout:
            original = parse_event_line(raw_line)
            if original is None:
                continue
            if original.get("type") == "system" and original.get("subtype") == "init":
                cli_sid = original.get("session_id")
                if cli_sid:
                    with session.lock:
                        session.cli_session_id = cli_sid
            if original.get("type") == "result":
                saw_result = True
            state.bus.publish(translate_event(original, session_id))
    finally:
        proc.wait()
        with session.lock:
            aborted = session.abort_requested
            session.proc = None
            session.abort_requested = False
        if not saw_result:
            state.bus.publish({
                "type": "result",
                "subtype": "aborted" if aborted else "error_during_execution",
                "is_error": True,
                "session_id": session_id,
            })


class Handler(BaseHTTPRequestHandler):
    state: ShimState  # setado em main() via subclasse dinâmica

    def log_message(self, fmt, *args):  # silencia o log padrão no stderr
        sys.stderr.write("[claude-code-shim] " + (fmt % args) + "\n")

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/session":
            session_id = self.state.create_session()
            self._send_json(200, {"id": session_id})
            return

        if path.endswith("/prompt") and path.startswith("/session/"):
            session_id = path[len("/session/"):-len("/prompt")]
            session = self.state.get_session(session_id)
            if session is None:
                self._send_json(404, {"error": f"sessão {session_id!r} não existe"})
                return
            body = self._json_body()
            prompt = body.get("prompt", "")
            model = body.get("model")
            self._send_json(202, {"accepted": True})
            threading.Thread(
                target=run_prompt, args=(self.state, session_id, session, prompt, model), daemon=True,
            ).start()
            return

        if path.endswith("/abort") and path.startswith("/session/"):
            session_id = path[len("/session/"):-len("/abort")]
            session = self.state.get_session(session_id)
            if session is None:
                self._send_json(404, {"error": f"sessão {session_id!r} não existe"})
                return
            with session.lock:
                session.abort_requested = True
                proc = session.proc
            if proc is not None:
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
            self._send_json(200, {"aborted": True})
            return

        self._send_json(404, {"error": "rota desconhecida"})

    def do_GET(self):
        if self.path.rstrip("/") != "/event":
            self._send_json(404, {"error": "rota desconhecida"})
            return
        q = self.state.bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                try:
                    envelope = q.get(timeout=1.0)
                except Empty:
                    continue
                chunk = f"data: {json.dumps(envelope)}\n\n".encode()
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.state.bus.unsubscribe(q)


def make_handler(state: ShimState):
    return type("BoundHandler", (Handler,), {"state": state})


def main() -> None:
    port = int(os.environ.get("CLAUDE_CODE_SHIM_PORT", "8091"))
    state = ShimState()
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(state))
    print(f"[claude-code-shim] listening on 0.0.0.0:{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
