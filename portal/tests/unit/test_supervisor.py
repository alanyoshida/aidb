"""Unitários do supervisor (task 4.2; tasks 2.1/2.2/2.3 do perfil de runtime):
backoff, mudança de arquivos, decisões, e subida do agente dirigida pelo perfil."""

import json
import os
import time

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


class FakeRunner:
    def __init__(self):
        self.spawned: list[tuple[list, str | None]] = []
        self.preexec_fns: list = []
        self.killed: list[int] = []
        self.dead: set[int] = set()
        self._next = 100

    def spawn(self, cmd, env=None, cwd=None, preexec_fn=None):
        self._next += 1
        self.spawned.append((cmd, cwd))
        self.preexec_fns.append(preexec_fn)
        return self._next

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
