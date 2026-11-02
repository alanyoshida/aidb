"""Unitários do supervisor (task 4.2): backoff, mudança de arquivos, decisões."""

import os
import time

from afsupervisor.supervisor import (
    Supervisor,
    app_entry_exists,
    backoff_seconds,
    dir_signature,
)


class FakeRunner:
    def __init__(self):
        self.spawned: list[tuple[list, str | None]] = []
        self.killed: list[int] = []
        self.dead: set[int] = set()
        self._next = 100

    def spawn(self, cmd, env=None, cwd=None):
        self._next += 1
        self.spawned.append((cmd, cwd))
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
    sup = Supervisor(runner=runner, workspace=str(tmp_path), app_port=8080)
    sup.start_harness()
    sup.start_app()
    assert sup.harness_pid is not None
    # placeholder: comando python -c com o código do placeholder
    cmds = [c for c, _ in runner.spawned]
    assert any("-c" in c for c in cmds)
    assert not any("main.py" in c for c in cmds)


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
