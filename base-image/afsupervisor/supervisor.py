"""Supervisor do container de sistema (PID 1) — ADR 0003.

Responsabilidades:
- subir o harness `opencode serve` (porta 4096 interna);
- gerir a app gerada em /workspace/app: sobe `python main.py` (cwd=app),
  reinicia com backoff em falha e reinicia quando arquivos mudam;
- servir um placeholder na porta da app enquanto não há app gerada, para a
  rota do edge responder com estado honesto.

Lógica de decisão (backoff, assinatura de mudança) é funções puras testáveis;
a classe Supervisor orquestra subprocessos via ProcessRunner (fake nos testes).
"""

import os
import signal
import subprocess
import sys
import time

HARNESS_CMD = ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]


def backoff_seconds(failures: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Backoff exponencial simples: 1s, 2s, 4s, ... cap 30s."""
    return min(cap, base * (2 ** max(0, failures - 1)))


def dir_signature(app_dir: str) -> tuple:
    """Assinatura (mtime, size) dos arquivos da app para detecção de mudanças."""
    sig = []
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__") and not d.startswith(".")]
        for f in files:
            path = os.path.join(root, f)
            try:
                st = os.stat(path)
                sig.append((path, st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                continue
    return tuple(sorted(sig))


def app_entry_exists(app_dir: str) -> bool:
    return os.path.isfile(os.path.join(app_dir, "main.py"))


_PLACEHOLDER_CODE = '''
import base64, hashlib, hmac, json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

SECRET = os.environ.get("APP_IDENTITY_SECRET", "")

def _identity(token):
    """Espelho de app_template.identity.resolve_identity (spec app-serving)."""
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

class R(BaseHTTPRequestHandler):
    def do_GET(self):
        token = parse_qs(urlparse(self.path).query).get("t", [None])[0]
        if _identity(token) is None:
            body = "AppAIForge: acesso restrito. Abra a app pelo portal.\\n".encode()
            self.send_response(403)
        else:
            body = "AppAIForge: app ainda nao gerada para este sistema.\\nUse o chat do portal.\\n".encode()
            self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", {port}), R).serve_forever()
'''


class ProcessRunner:
    """Abstração mínima sobre subprocess; testes injetam um fake.

    Guarda os Popen para reap automático (poll() colhe zumbis) e para saber
    o estado real dos filhos — kill(pid, 0) consideraria zumbi vivo.
    """

    def __init__(self) -> None:
        self._children: dict[int, subprocess.Popen] = {}

    def spawn(self, cmd: list[str], env: dict | None = None, cwd: str | None = None) -> int:
        popen = subprocess.Popen(
            cmd, env=env, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        self._children[popen.pid] = popen
        return popen.pid

    def alive(self, pid: int) -> bool:
        popen = self._children.get(pid)
        if popen is None:
            return False
        return popen.poll() is None

    def kill(self, pid: int) -> None:
        popen = self._children.pop(pid, None)
        if popen is not None and popen.poll() is None:
            popen.terminate()
            try:
                popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                popen.kill()


class Supervisor:
    def __init__(self, runner: ProcessRunner | None = None,
                 workspace: str = "/workspace", app_port: int = 8080,
                 root_path: str | None = None):
        self.runner = runner or ProcessRunner()
        self.workspace = workspace
        self.app_dir = os.path.join(workspace, "app")
        self.app_port = app_port
        self.root_path = root_path or os.environ.get("APP_ROOT_PATH", "/")
        self.harness_pid: int | None = None
        self.app_pid: int | None = None
        self.app_failures = 0
        self.is_placeholder = True
        self._signature: tuple | None = dir_signature(self.app_dir) if app_entry_exists(self.app_dir) else None

    def start_harness(self) -> None:
        self.harness_pid = self.runner.spawn(HARNESS_CMD)

    def app_python(self) -> str:
        """Python da app: venv criado pelo agente (uv) quando existir, senão o do sistema."""
        venv_python = os.path.join(self.app_dir, ".venv", "bin", "python")
        return venv_python if os.path.isfile(venv_python) else sys.executable

    def start_app(self) -> None:
        if self.app_pid is not None:
            self.runner.kill(self.app_pid)
            self.app_pid = None
        if app_entry_exists(self.app_dir):
            env = {**os.environ, "PORT": str(self.app_port), "APP_ROOT_PATH": self.root_path}
            self.app_pid = self.runner.spawn([self.app_python(), "main.py"], env=env, cwd=self.app_dir)
            self._signature = dir_signature(self.app_dir)
            self.is_placeholder = False
        else:
            self.app_pid = self.runner.spawn(
                [sys.executable, "-c", _PLACEHOLDER_CODE.format(port=self.app_port)]
            )
            self.is_placeholder = True

    def poll(self) -> None:
        """Um passo da malha de controle: reinicia a app se morreu, mudou ou apareceu."""
        if self.app_pid is not None and not self.runner.alive(self.app_pid):
            self.app_failures += 1
            self.app_pid = None

        has_app = app_entry_exists(self.app_dir)
        if has_app:
            if self.app_pid is None:
                if self.app_failures:
                    time.sleep(backoff_seconds(self.app_failures))
                self.start_app()
                return
            sig = dir_signature(self.app_dir)
            changed = self._signature is not None and sig != self._signature
            if self.is_placeholder or changed:
                self.start_app()
            else:
                self._signature = sig
        else:
            if self.app_pid is None:
                self.start_app()
            elif not self.is_placeholder:
                self.start_app()  # app removida (rollback): volta ao placeholder

    def run_forever(self, poll_interval: float = 1.0) -> None:
        self.start_harness()
        self.start_app()
        while True:
            time.sleep(poll_interval)
            self.poll()


def main() -> None:
    port = int(os.environ.get("APP_PORT", "8080"))
    Supervisor(app_port=port).run_forever()


if __name__ == "__main__":
    main()
