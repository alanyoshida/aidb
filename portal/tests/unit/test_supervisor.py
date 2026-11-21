"""Unitários do supervisor (task 4.2; tasks 2.1/2.2/2.3 do perfil de runtime):
backoff, mudança de arquivos, decisões, e subida do agente dirigida pelo perfil."""

import json
import os
import time

import pytest

from afsupervisor import supervisor as _supervisor_module
from afsupervisor.supervisor import (
    Supervisor,
    app_entry_exists,
    backoff_seconds,
    dir_signature,
    load_agent_profile,
)

FAKE_PROFILE = {
    "command": ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"],
    "cwd": "/opencode-config",
}


@pytest.fixture(autouse=True)
def _pid_file(tmp_path, monkeypatch):
    path = tmp_path / "aidb-app.pid"
    monkeypatch.setattr(_supervisor_module, "APP_PID_FILE", str(path))
    return path


class FakeRunner:
    def __init__(self):
        self.spawned: list[tuple[list, str | None]] = []
        self.preexec_fns: list = []
        self.killed: list[int] = []
        self.dead: set[int] = set()
        self._next = 100
        self.ran: list[tuple[list, str | None, float | None]] = []
        self.run_result: int | Exception = 0

    def spawn(self, cmd, env=None, cwd=None, preexec_fn=None):
        self._next += 1
        self.spawned.append((cmd, cwd))
        self.preexec_fns.append(preexec_fn)
        return self._next

    def run(self, cmd, cwd=None, timeout=None):
        self.ran.append((cmd, cwd, timeout))
        if isinstance(self.run_result, Exception):
            raise self.run_result
        return self.run_result

    def alive(self, pid):
        return pid not in self.dead

    def kill(self, pid):
        self.killed.append(pid)
        self.dead.add(pid)


def test_backoff_exponencial_com_teto():
    assert backoff_seconds(0) == 1.0
    assert backoff_seconds(1) == 1.0
    assert backoff_seconds(2) == 2.0
    assert backoff_seconds(3) == 4.0
    assert backoff_seconds(10) == 30.0  # cap


def test_assinatura_muda_quando_arquivo_muda(tmp_path):
    (tmp_path / "main.py").write_text("print('v1')\n")
    sig1 = dir_signature(str(tmp_path))
    time.sleep(0.01)
    (tmp_path / "main.py").write_text("print('v2 agora maior')\n")
    sig2 = dir_signature(str(tmp_path))
    assert sig1 != sig2


def test_supervisor_sobe_placeholder_sem_app(tmp_path):
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=8080, agent_profile=FAKE_PROFILE)
    sup.start_harness()
    sup.start_app()
    assert sup.harness_pid is not None
    # placeholder: comando python -c com o código do placeholder
    cmds = [c for c, _ in runner.spawned]
    assert any("-c" in c for c in cmds)
    assert not any("main.py" in c for c in cmds)


def test_supervisor_sobe_agente_conforme_o_perfil(tmp_path):
    """Task 2.1: comando e cwd do harness vêm do perfil, não de constante embutida."""
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
    sup.start_harness()
    assert sup.harness_pid is not None
    assert sup.harness_failed is False
    cmd, cwd = runner.spawned[0]
    assert cmd == FAKE_PROFILE["command"]
    assert cwd == FAKE_PROFILE["cwd"]


def test_supervisor_outro_perfil_sobe_outro_comando(tmp_path):
    """Conjunto de perfis extensível: trocar o perfil troca o comando sem tocar o supervisor."""
    runner = FakeRunner()
    outro_perfil = {"command": ["um-outro-agente", "serve"], "cwd": "/outro-config"}
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=outro_perfil)
    sup.start_harness()
    cmd, cwd = runner.spawned[0]
    assert cmd == ["um-outro-agente", "serve"]
    assert cwd == "/outro-config"


def test_supervisor_sandboxed_instala_confinamento_antes_do_spawn_do_agente(tmp_path):
    """Task 6.1: em modo sandboxed, o confinamento é passado como preexec_fn
    (roda no filho, entre o fork e o exec) — nunca no processo do supervisor."""
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE, execution_mode="sandboxed")
    sup.start_harness()
    assert sup.harness_failed is False
    assert sup.harness_pid is not None
    assert runner.preexec_fns[0] is not None


def test_supervisor_sandboxed_confinamento_falha_impede_subida_do_agente(tmp_path, monkeypatch):
    """Task 6.2: confinamento sandboxed que falha é falha explícita — mesmo
    contrato de perfil ausente, nunca sobe o agente menos confinado."""

    class FailingRunner(FakeRunner):
        def spawn(self, cmd, env=None, cwd=None, preexec_fn=None):
            if preexec_fn is not None:
                raise OSError("landlock_restrict_self")
            return super().spawn(cmd, env=env, cwd=cwd, preexec_fn=preexec_fn)

    runner = FailingRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE, execution_mode="sandboxed")
    sup.start_harness()
    assert sup.harness_failed is True
    assert sup.harness_pid is None


def test_supervisor_reduced_e_legacy_sobem_sem_confinamento(tmp_path):
    """Task 6.3: regressão da etapa 1 — modos reduced/legacy continuam subindo
    o agente sem seccomp/Landlock (preexec_fn=None)."""
    for mode in ("reduced", "legacy"):
        runner = FakeRunner()
        sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE, execution_mode=mode)
        sup.start_harness()
        assert sup.harness_failed is False
        assert sup.harness_pid is not None
        assert runner.preexec_fns[0] is None


def test_supervisor_sem_perfil_nao_sobe_agente_nenhum(tmp_path):
    """Task 2.2: perfil ausente é falha explícita, nunca um agente embutido."""
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=None)
    sup.start_harness()
    assert sup.harness_pid is None
    assert sup.harness_failed is True
    assert runner.spawned == []


def test_load_agent_profile_caminho_ausente_devolve_none():
    assert load_agent_profile(None) is None
    assert load_agent_profile("") is None


def test_load_agent_profile_arquivo_inexistente_devolve_none(tmp_path):
    assert load_agent_profile(str(tmp_path / "nao-existe.json")) is None


def test_load_agent_profile_json_invalido_devolve_none(tmp_path):
    bad = tmp_path / "ruim.json"
    bad.write_text("{nao e json valido")
    assert load_agent_profile(str(bad)) is None


def test_load_agent_profile_le_perfil_valido(tmp_path):
    good = tmp_path / "perfil.json"
    good.write_text(json.dumps(FAKE_PROFILE))
    assert load_agent_profile(str(good)) == FAKE_PROFILE


def test_supervisor_run_forever_nao_falha_sem_perfil_e_app_sobe(tmp_path, monkeypatch):
    """Task 2.3: app gerada/placeholder sobem independentemente do perfil do agente."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('oi')\n")
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=9000, agent_profile=None)

    calls = {"n": 0}

    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", fake_sleep)
    try:
        sup.run_forever(poll_interval=0)
    except KeyboardInterrupt:
        pass
    assert sup.harness_failed is True
    assert sup.app_pid is not None
    assert "main.py" in str(runner.spawned[-1][0][-1])


def test_supervisor_sobe_app_e_detecta_mudanca(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('oi')\n")
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=9000)
    sup.start_app()
    assert ("main.py", str(app)) in [(os.path.basename(c[0][1]) if len(c) > 1 else None, c[1]) for c in runner.spawned]
    # muda arquivo -> poll reinicia a app
    before = len(runner.spawned)
    (app / "main.py").write_text("print('novo')\n")
    sup.poll()
    assert len(runner.spawned) == before + 1
    # e matou a anterior
    assert len(runner.killed) == 1


def test_supervisor_reinicia_app_morta_com_contagem(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('oi')\n")
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=9000)
    sup.start_app()
    first_pid = sup.app_pid
    runner.dead.add(first_pid)  # app "morre"
    sup.poll()
    assert sup.app_failures == 1
    assert sup.app_pid not in (None, first_pid)


def test_supervisor_volta_ao_placeholder_quando_app_removida(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('oi')\n")
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=9000)
    sup.start_app()
    assert "main.py" in str(runner.spawned[-1])
    (app / "main.py").unlink()
    sup.poll()
    cmds = [c for c, _ in runner.spawned]
    assert any("-c" in c for c in cmds[-1:])  # último spawn é o placeholder


def test_supervisor_troca_placeholder_pela_app_quando_ela_aparece(tmp_path):
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=9000)
    sup.start_app()
    assert sup.is_placeholder
    # app aparece no workspace -> próximo poll a sobe no lugar do placeholder
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('surgiu')\n")
    sup.poll()
    assert not sup.is_placeholder
    assert "main.py" in str(runner.spawned[-1][0][-1])


# --- bootstrap do OpenSpec (change add-openspec-to-system-container, task 2.1) ---

def test_openspec_workspace_vazio_faz_init_em_pt_br(tmp_path):
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
    assert sup.ensure_openspec() == "init"
    cmd, cwd, timeout = runner.ran[0]
    assert cmd == ["openspec", "init", "--tools", "opencode", "--language", "pt-BR", str(tmp_path)]
    assert cwd == str(tmp_path) and timeout == 30


def test_openspec_workspace_inicializado_faz_update(tmp_path):
    (tmp_path / "openspec" / "changes" / "minha-change").mkdir(parents=True)
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
    assert sup.ensure_openspec() == "update"
    assert runner.ran[0][0] == ["openspec", "update", str(tmp_path)]


def test_openspec_roda_antes_do_harness(tmp_path, monkeypatch):
    import afsupervisor.supervisor as mod

    order = []
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
    monkeypatch.setattr(sup, "ensure_openspec", lambda: order.append("openspec"))
    monkeypatch.setattr(sup, "start_harness", lambda: order.append("harness"))
    monkeypatch.setattr(sup, "start_app", lambda: order.append("app"))
    monkeypatch.setattr(mod.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        sup.run_forever()
    except KeyboardInterrupt:
        pass
    assert order == ["openspec", "harness", "app"]


def test_openspec_falha_ou_timeout_nao_impede_o_harness(tmp_path, capsys):
    import subprocess

    for erro in (subprocess.TimeoutExpired(["openspec"], 30), FileNotFoundError("openspec"), 1):
        runner = FakeRunner()
        runner.run_result = erro
        sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
        assert sup.ensure_openspec() == "failed"
        sup.start_harness()
        assert sup.harness_pid is not None and not sup.harness_failed
    assert "openspec init" in capsys.readouterr().err


def test_openspec_liga_comandos_do_workspace_no_diretorio_global_do_opencode(tmp_path, monkeypatch):
    """O opencode do sistema roda em /opencode-config (fora do workspace, para o agente não
    alterar a própria config) e por isso não lê `/workspace/.opencode/`. Só os comandos são
    expostos, pelo diretório global de comandos do opencode — nunca a config do projeto."""
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    (ws / ".opencode" / "commands").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    sup = Supervisor(runner=FakeRunner(), workspace=str(ws), agent_profile=FAKE_PROFILE)
    assert sup.ensure_openspec() == "init"
    link = home / ".config" / "opencode" / "commands"
    assert link.is_symlink() and os.readlink(link) == str(ws / ".opencode" / "commands")
    # idempotente em reinícios
    assert sup.ensure_openspec() in ("init", "update")
    assert link.is_symlink()


def test_openspec_nao_sobrescreve_diretorio_global_real(tmp_path, monkeypatch):
    home = tmp_path / "home"
    real = home / ".config" / "opencode" / "commands"
    real.mkdir(parents=True)
    (real / "meu.md").write_text("x")
    ws = tmp_path / "ws"
    (ws / ".opencode" / "commands").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    Supervisor(runner=FakeRunner(), workspace=str(ws), agent_profile=FAKE_PROFILE).ensure_openspec()
    assert not real.is_symlink() and (real / "meu.md").exists()


def test_supervisor_so_implantacao_sobe_so_a_app(tmp_path):
    """change add-deploy-only-system, tarefa 2.1: sem harness e sem OpenSpec, só a app."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('app')\n")
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE,
                     system_kind="deploy_only")
    sup.start()
    assert sup.harness_pid is None
    assert runner.ran == [], "nenhum comando de preparação (OpenSpec) roda"
    assert len(runner.spawned) == 1
    cmd, cwd = runner.spawned[0]
    assert cmd[-1] == "main.py" and cwd == str(app)
    assert not (tmp_path / "openspec").exists()


def test_supervisor_com_agente_continua_subindo_harness(tmp_path):
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE)
    sup.start()
    assert sup.harness_pid is not None
    assert any(cmd == FAKE_PROFILE["command"] for cmd, _ in runner.spawned)


def test_supervisor_grava_o_pid_da_app_a_cada_subida(tmp_path, _pid_file):
    """O portal compara o PID antes e depois de implantar (add-deploy-only-system, D5)."""
    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE, system_kind="deploy_only")
    sup.start()
    assert _pid_file.read_text().split() == [str(sup.app_pid), "placeholder"]
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("print('app')\n")
    sup.poll()
    assert _pid_file.read_text().split() == [str(sup.app_pid), "app"]


def _placeholder_text(tmp_path, system_kind: str) -> str:
    """Sobe o código do placeholder de verdade e lê a página com um token legado válido."""
    import base64
    import hashlib
    import hmac
    import socket
    import subprocess
    import sys
    import urllib.request

    runner = FakeRunner()
    sup = Supervisor(runner=runner, workspace=str(tmp_path), agent_profile=FAKE_PROFILE,
                     system_kind=system_kind)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        sup.app_port = s.getsockname()[1]
    sup.start_app()
    cmd = next(c for c, _ in runner.spawned if "-c" in c)
    secret = "segredo-de-teste"
    body = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 60}).encode()).decode().rstrip("=")
    token = body + "." + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    proc = subprocess.Popen([sys.executable, *cmd[1:]], env={**os.environ, "APP_IDENTITY_SECRET": secret})
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{sup.app_port}/?t={token}", timeout=1) as r:
                    return r.read().decode()
            except OSError:
                time.sleep(0.1)
        raise AssertionError("placeholder não respondeu")
    finally:
        proc.kill()
        proc.wait()


def test_placeholder_de_sistema_com_agente_aponta_para_o_chat(tmp_path):
    text = _placeholder_text(tmp_path, "agent")
    assert "ainda nao gerada" in text and "chat do portal" in text


def test_placeholder_de_sistema_so_implantacao_aponta_para_a_aba_implantacao(tmp_path):
    text = _placeholder_text(tmp_path, "deploy_only")
    assert "chat" not in text
    assert "nenhuma versao implantada" in text and "aba Implantacao" in text
