"""FakeHarness (ADR 0016): reproduz o padrão de eventos do opencode sem LLM.

Usado na suíte E2E para determinismo: grava arquivos reais no workspace (a app
de exemplo entra no ar de verdade), emite a sequência normalizada de eventos e
retorna uso de tokens fixo.
"""

import os
import time

from .base import HarnessPort, RunEvent

_SAMPLE_APP = '''"""App de exemplo gerada pelo FakeHarness (E2E) — com gate de identidade."""
import base64, hashlib, hmac, json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

SECRET = os.environ.get("APP_IDENTITY_SECRET", "")
SLUG = os.environ.get("APPAIFORGE_SLUG", "__SLUG__")


def _identity(token):
    if not SECRET or not token:
        return None
    try:
        body_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        token = parse_qs(urlparse(self.path).query).get("t", [None])[0]
        user = _identity(token)
        if user is None:
            body = "AppAIForge: acesso restrito. Abra a app pelo portal.\\n".encode()
            self.send_response(403)
        else:
            body = f"App de exemplo do sistema {SLUG} — ola, {user.get('user_id', '?')[:8]}!\\n".encode()
            self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
'''


class FakeHarness(HarnessPort):
    def __init__(self, workspace_root: str, step_delay: float | None = None):
        import os

        if step_delay is None:
            step_delay = float(os.environ.get("APPAIFORGE_FAKE_DELAY", "0.15"))
        self.workspace_root = workspace_root
        self.step_delay = step_delay
        self._interrupted: set[str] = set()
        self.decisions: dict[str, bool] = {}  # gate: request_id -> aprovado?
        self.counter = 0

    def create_session(self, system: dict) -> str:
        self.counter += 1
        return f"ses_fake_{self.counter:06d}"

    def interrupt(self, system: dict, session_id: str) -> None:
        self._interrupted.add(session_id)

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        self.decisions[request_id] = approve

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started", meta={"session_id": session_id}))
        time.sleep(self.step_delay)
        on_event(RunEvent("message", text="⚠️ MODO FAKE (sem LLM): esta é uma resposta simulada de teste. "
                                          "Para conversar com o agente real, suba o portal com APPAIFORGE_HARNESS_MODE=opencode."))
        time.sleep(self.step_delay)
        on_event(RunEvent("message", text=f"Entendi o pedido: {prompt[:80]}"))

        slug = system.get("slug", "sistema")

        # cenários do gate (spec destructive-gate, verificação E2E)
        upper = prompt.upper()
        if "TRUNCATE" in upper or "DELETE SEM WHERE" in upper:
            destructive = "TRUNCATE TABLE clientes" if "TRUNCATE" in upper else "DELETE FROM clientes"
            self.counter += 1
            request_id = f"per_fake_{self.counter:06d}"
            command = f'psql "$DATABASE_URL_VENDAS" -c "{destructive}"'
            on_event(RunEvent("gate_request", text=command, meta={
                "request_id": request_id, "session_id": session_id, "permission": "bash",
            }))
            deadline = time.time() + 120
            while request_id not in self.decisions and time.time() < deadline:
                time.sleep(0.2)
            approved = self.decisions.get(request_id, False)
            if approved:
                on_event(RunEvent("message", text=f"Operação aprovada pelo gate: {destructive}"))
                on_event(RunEvent("run_finished", meta={"summary": f"Operação destrutiva executada com aprovação: {destructive}"}))
            else:
                on_event(RunEvent("message", text=f"Operação recusada pelo gate: {destructive}"))
                on_event(RunEvent("run_finished", meta={"summary": f"Operação destrutiva recusada pelo gate: {destructive}"}))
            return

        workspace = os.path.join(self.workspace_root, slug)
        app_dir = os.path.join(workspace, "app")
        os.makedirs(app_dir, exist_ok=True)
        app_file = os.path.join(app_dir, "main.py")
        with open(app_file, "w") as f:
            f.write(_SAMPLE_APP.replace("__SLUG__", slug))
        time.sleep(self.step_delay)
        on_event(RunEvent("file_edited", text="app/main.py", meta={"files": [app_file]}))
        on_event(RunEvent("command_run", text="python -m compileall .", meta={"command": "compileall"}))

        if session_id in self._interrupted:
            self._interrupted.discard(session_id)
            on_event(RunEvent("run_interrupted"))
            return

        time.sleep(self.step_delay)
        on_event(RunEvent(
            "usage",
            meta={"provider": "fake", "model": "fake-1", "input_tokens": 120, "output_tokens": 80},
        ))
        on_event(RunEvent("message", text="Pronto: app de exemplo criada e servida."))
        on_event(RunEvent("run_finished", meta={"summary": "App de exemplo criada e servida."}))
