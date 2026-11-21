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


APP_PID_FILE = os.environ.get("AIDB_APP_PID_FILE", "/tmp/aidb-app.pid")


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
AUD = "aidb-app:" + os.environ.get("APPAIFORGE_SLUG", "")


def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _identity(token):
    """Espelho de app_template.identity.verify_identity (spec app-serving): JWT HS256
    do header X-AIDB-Identity, emitido pelo portal para ESTA app."""
    if not SECRET or not token:
        return None
    try:
        h, p, sig = token.split(".")
        if json.loads(_b64(h)).get("alg") != "HS256":
            return None
        expected = hmac.new(SECRET.encode(), (h + "." + p).encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64(sig)):
            return None
        claims = json.loads(_b64(p))
        aud = claims.get("aud")
        if claims.get("iss") != "aidb-portal" or AUD not in (aud if isinstance(aud, list) else [aud]):
            return None
        if int(claims.get("exp", 0)) < time.time():
            return None
        return claims
    except Exception:
        return None


def _legacy(token):
    """Handoff legado ?t= (ADR 0006) — mantido para portais anteriores ao forwardAuth."""
    if not SECRET or not token:
        return None
    try:
        body_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64(body_b64))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


class R(BaseHTTPRequestHandler):
    def do_GET(self):
        legacy = parse_qs(urlparse(self.path).query).get("t", [None])[0]
        if _identity(self.headers.get("X-AIDB-Identity")) is None and _legacy(legacy) is None:
            body = "AIDB: acesso restrito. Abra a app pelo portal.\\n".encode()
            self.send_response(401)
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


OPENSPEC_TIMEOUT_SECONDS = 30


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

    def run(self, cmd: list[str], cwd: str | None = None, timeout: float | None = None) -> int:
        """Execução síncrona (passos de preparo do workspace); levanta TimeoutExpired."""
        return subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=timeout,
        ).returncode

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
                 execution_mode: str = "legacy", system_kind: str = "agent"):
        self.runner = runner or ProcessRunner()
        self.workspace = workspace
        self.app_dir = os.path.join(workspace, "app")
        self.app_port = app_port
        self.root_path = root_path or os.environ.get("APP_ROOT_PATH", "/")
        self.agent_profile = agent_profile
        self.execution_mode = execution_mode
        # `deploy_only` (change add-deploy-only-system): sistema que só implanta versões
        # aprovadas — nenhum agente, nenhum OpenSpec no workspace, só a app.
        self.system_kind = system_kind
        self.harness_pid: int | None = None
        self.harness_failed = False
        self.app_pid: int | None = None
        self.app_failures = 0
        self.is_placeholder = True
        self._signature: tuple | None = dir_signature(self.app_dir) if app_entry_exists(self.app_dir) else None

    def ensure_openspec(self) -> str:
        """Deixa o workspace com OpenSpec configurado para o opencode (change
        add-openspec-to-system-container, D2), antes do harness subir.

        Sem `openspec/`: `openspec init --tools opencode --language pt-BR`. Com `openspec/`:
        `openspec update`, que só atualiza comandos e skills do agente e preserva changes,
        specs e config. Roda com a mesma identidade do harness (o próprio supervisor), então
        os arquivos ficam com o dono certo nos dois drivers. Qualquer falha — CLI ausente,
        erro ou timeout de 30 s — só é registrada: agente e app sobem do mesmo jeito.
        Devolve "init", "update" ou "failed"."""
        try:
            return self._openspec_cli()
        finally:
            self._link_agent_commands()

    def _link_agent_commands(self) -> None:
        """Expõe `/workspace/.opencode/commands` no diretório GLOBAL de comandos do opencode.

        O opencode do sistema roda em `/opencode-config` (fora do workspace, para o agente não
        alterar a própria config — ADR 0018) e por isso não lê o `.opencode/` do workspace; só
        os comandos (prompts em markdown) são expostos aqui, nunca a config do projeto. Fica na
        camada gravável do container (HOME), refeito a cada subida. Um diretório real já
        existente nesse lugar não é sobrescrito."""
        source = os.path.join(self.workspace, ".opencode", "commands")
        if not os.path.isdir(source):
            return
        link = os.path.join(os.path.expanduser("~"), ".config", "opencode", "commands")
        try:
            if os.path.islink(link):
                if os.readlink(link) == source:
                    return
                os.unlink(link)
            elif os.path.exists(link):
                print(f"[afsupervisor] {link} já existe e não é link; comandos do OpenSpec não expostos",
                      file=sys.stderr)
                return
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(source, link)
        except OSError as exc:
            print(f"[afsupervisor] não foi possível expor os comandos do agente: {exc!r}", file=sys.stderr)

    def _openspec_cli(self) -> str:
        initialized = os.path.isdir(os.path.join(self.workspace, "openspec"))
        if initialized:
            action, cmd = "update", ["openspec", "update", self.workspace]
        else:
            action = "init"
            cmd = ["openspec", "init", "--tools", "opencode", "--language", "pt-BR", self.workspace]
        try:
            returncode = self.runner.run(cmd, cwd=self.workspace, timeout=OPENSPEC_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - bootstrap nunca derruba o sistema
            print(f"[afsupervisor] openspec {action} falhou: {exc!r}; seguindo sem bloquear", file=sys.stderr)
            return "failed"
        if returncode != 0:
            print(f"[afsupervisor] openspec {action} saiu com código {returncode}; seguindo sem bloquear",
                  file=sys.stderr)
            return "failed"
        print(f"[afsupervisor] openspec {action} ok", file=sys.stderr)
        return action

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
        self._record_app_start()

    def _record_app_start(self) -> None:
        """Grava o PID da app em APP_PID_FILE (melhor esforço): o portal compara antes e depois
        de implantar uma versão para saber que a app nova já subiu (add-deploy-only-system, D5)."""
        try:
            with open(APP_PID_FILE + ".tmp", "w") as f:
                f.write(f"{self.app_pid} {'placeholder' if self.is_placeholder else 'app'}\n")
            os.replace(APP_PID_FILE + ".tmp", APP_PID_FILE)
        except OSError:
            pass

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

    def start(self) -> None:
        if self.system_kind != "deploy_only":
            self.ensure_openspec()
            self.start_harness()
        self.start_app()

    def run_forever(self, poll_interval: float = 1.0) -> None:
        self.start()
        while True:
            time.sleep(poll_interval)
            self.poll()


def main() -> None:
    port = int(os.environ.get("APP_PORT", "8080"))
    profile = load_agent_profile(os.environ.get("AIDB_AGENT_PROFILE"))
    execution_mode = os.environ.get("AIDB_EXECUTION_MODE", "legacy")
    system_kind = os.environ.get("AIDB_SYSTEM_KIND", "agent")
    Supervisor(app_port=port, agent_profile=profile, execution_mode=execution_mode,
               system_kind=system_kind).run_forever()


if __name__ == "__main__":
    main()
