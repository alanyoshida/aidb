"""Supervisor do container de sistema (PID 1) — ADR 0003, ADR 0018.

Responsabilidades:
- subir o agente conforme o perfil de runtime (capability agent-runtime)
  apontado por AIDB_AGENT_PROFILE — o supervisor não embute comando, cwd nem
  porta de nenhum agente específico;
- gerir a app gerada em /workspace/app: sobe `python main.py` (cwd=app),
  reinicia com backoff em falha e reinicia quando arquivos mudam;
- servir um placeholder na porta da app enquanto não há app gerada, para a
  rota do edge responder com estado honesto.

Lógica de decisão (backoff, assinatura de mudança) é funções puras testáveis;
a classe Supervisor orquestra subprocessos via ProcessRunner (fake nos testes).
"""

import json
import os
import signal
import subprocess
import sys
import time


def load_agent_profile(path: str | None) -> dict | None:
    """Carrega o perfil de runtime do agente do caminho em AIDB_AGENT_PROFILE.

    Devolve None quando o caminho não está definido, o arquivo não existe ou
    não é um JSON válido — o chamador trata isso como falha explícita, nunca
    recorrendo silenciosamente a um agente padrão embutido (spec agent-runtime)."""
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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
            body = "AIDB: acesso restrito. Abra a app pelo portal.\\n".encode()
            self.send_response(403)
        else:
            body = "AIDB: app ainda nao gerada para este sistema.\\nUse o chat do portal.\\n".encode()
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

    def spawn(self, cmd: list[str], env: dict | None = None, cwd: str | None = None,
              preexec_fn=None) -> int:
        """`preexec_fn`, quando dado, roda no filho entre o fork e o exec —
        é aí que o confinamento sandboxed é instalado, nunca no processo do
        supervisor em si (que precisa continuar operando sem a restrição
        pensada para o agente). Uma exceção levantada dentro de `preexec_fn`
        é propagada de volta para este processo pelo próprio `subprocess`,
        então nunca falha silenciosamente no filho."""
        popen = subprocess.Popen(
            cmd, env=env, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            preexec_fn=preexec_fn,
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
                 root_path: str | None = None, agent_profile: dict | None = None,
                 execution_mode: str = "legacy"):
        self.runner = runner or ProcessRunner()
        self.workspace = workspace
        self.app_dir = os.path.join(workspace, "app")
        self.app_port = app_port
        self.root_path = root_path or os.environ.get("APP_ROOT_PATH", "/")
        self.agent_profile = agent_profile
        self.execution_mode = execution_mode
        self.harness_pid: int | None = None
        self.harness_failed = False
        self.app_pid: int | None = None
        self.app_failures = 0
        self.is_placeholder = True
        self._signature: tuple | None = dir_signature(self.app_dir) if app_entry_exists(self.app_dir) else None

    def start_harness(self) -> None:
        if self.agent_profile is None:
            self.harness_failed = True
            print(
                "[afsupervisor] perfil de agente ausente ou ilegível (AIDB_AGENT_PROFILE); "
                "harness não iniciado",
                file=sys.stderr,
            )
            return
        confine = None
        if self.execution_mode == "sandboxed":
            # Roda no filho entre o fork e o exec (preexec_fn) — confina o
            # processo do agente e tudo que ele gerar, sem restringir o
            # supervisor (PID 1), que precisa continuar livre para gerenciar
            # a app depois (capability agent-sandbox, etapa 2).
            from . import sandbox

            confine = lambda: sandbox.apply_sandbox(self.agent_profile, sandbox.DEFAULT_DENY_SYSCALLS)  # noqa: E731
        try:
            self.harness_pid = self.runner.spawn(
                self.agent_profile["command"], cwd=self.agent_profile["cwd"], preexec_fn=confine,
            )
        except Exception as exc:
            # modo sandboxed promete confinamento; nunca sobe o agente menos
            # confinado do que o modo diz, mesmo que o host devesse suportar
            # Landlock (o portal já sondou o mesmo kernel antes de persistir
            # este modo) — mesmo contrato de perfil ausente.
            if confine is None:
                raise
            self.harness_failed = True
            print(
                f"[afsupervisor] confinamento sandboxed falhou ({exc}); harness não iniciado",
                file=sys.stderr,
            )

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
    profile = load_agent_profile(os.environ.get("AIDB_AGENT_PROFILE"))
    execution_mode = os.environ.get("AIDB_EXECUTION_MODE", "legacy")
    Supervisor(app_port=port, agent_profile=profile, execution_mode=execution_mode).run_forever()


if __name__ == "__main__":
    main()
