"""Unitários do dispatch de eventos em agent_queue.py: deduplicação de updates
repetidos do harness (bugs relatados: comando/uso duplicado no chat e na
auditoria) e roteamento de permission.asked por tipo (bug relatado: pedido de
acesso a diretório tratado como se fosse SQL, com "comando: comando" vazio)."""

import time

import pytest

from appaiforge import auth
from appaiforge.agent_queue import AgentQueue
from appaiforge.db import session_scope
from appaiforge.harness.base import HarnessPort, RunEvent
from appaiforge.models import AgentRun, RunStatus, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _wait_run(queue: AgentQueue, run_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run and run.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
                return
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


class ScriptedHarness(HarnessPort):
    """Harness que repete exatamente a sequência de eventos observada do
    opencode real: um comando emitido 2x (mesmo texto, antes do output
    chegar), um "usage" repetido seguido de um com zeros, e um command_run
    com comando ainda vazio (estado pendente antes do input ser preenchido)."""

    def __init__(self):
        self.replied: list[tuple[str, bool]] = []

    def create_session(self, system: dict) -> str:
        return "ses_scripted"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        self.replied.append((request_id, approve))

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("command_run", text="", meta={"command": ""}))  # estado pendente, sem comando
        on_event(RunEvent("command_run", text="", meta={"command": "ls -la"}))
        on_event(RunEvent("command_run", text="", meta={"command": "ls -la"}))  # mesmo update reemitido
        on_event(RunEvent("command_run", text="total 0", meta={"command": "ls -la"}))  # output chega
        on_event(RunEvent("usage", meta={"input_tokens": 100, "output_tokens": 10}))
        on_event(RunEvent("usage", meta={"input_tokens": 100, "output_tokens": 10}))  # reemitido
        on_event(RunEvent("usage", meta={"input_tokens": 0, "output_tokens": 0}))  # trailing zerado
        on_event(RunEvent("run_finished"))


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("dispatch@t.local", "pw", UserType.editor.value)


def test_dedup_colapsa_comando_e_usage_repetidos(editor, fake_workspace):
    harness = ScriptedHarness()
    queue = AgentQueue(harness)
    system = create_system(editor, "Dispatch", "dispatch-dedup")
    run = queue.enqueue(system.id, editor.id, "faça algo", chat_session_id=None)
    _wait_run(queue, run.id)

    events = queue.buffers[run.id].snapshot()
    command_runs = [e for e in events if e.kind == "command_run"]
    usages = [e for e in events if e.kind == "usage"]

    # o command_run com comando vazio (estado pendente) não aparece
    assert all((e.meta.get("command") or "").strip() for e in command_runs)
    # o update repetido ("ls -la" sem output, duas vezes seguidas) colapsa em um só;
    # o que chega depois com output é um evento genuinamente diferente (texto mudou)
    assert len(command_runs) == 2
    assert [e.meta["command"] for e in command_runs] == ["ls -la", "ls -la"]

    # o usage repetido colapsa, e o usage zerado (trailing) nunca aparece
    assert len(usages) == 1
    assert usages[0].meta["input_tokens"] == 100


def test_usage_nao_e_contado_em_dobro_no_banco(editor, fake_workspace):
    from appaiforge.models import TokenUsage
    from sqlalchemy import select

    harness = ScriptedHarness()
    queue = AgentQueue(harness)
    system = create_system(editor, "Dispatch2", "dispatch-usage")
    run = queue.enqueue(system.id, editor.id, "faça algo", chat_session_id=None)
    _wait_run(queue, run.id)

    with session_scope() as s:
        rows = s.execute(select(TokenUsage).where(TokenUsage.run_id == run.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].input_tokens == 100
    assert rows[0].output_tokens == 10


class NonBashPermissionHarness(HarnessPort):
    """Simula o opencode pedindo permissão para algo que não é bash/SQL
    (ex.: external_directory) — bug relatado: virava "comando de banco" vazio."""

    def __init__(self):
        self.replied: list[tuple[str, bool]] = []

    def create_session(self, system: dict) -> str:
        return "ses_nonbash"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        self.replied.append((request_id, approve))

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("gate_request", text="", meta={
            "request_id": "per_ext_1", "session_id": session_id, "permission": "external_directory",
        }))
        # a run fica presa aguardando decide_gate(); o teste decide e segue


@pytest.fixture()
def nonbash_editor(clean_db):
    return auth.create_user("nonbash@t.local", "pw", UserType.editor.value)


def test_permissao_nao_bash_nao_vira_decisao_de_sql(nonbash_editor, fake_workspace):
    from appaiforge.services import audit as _unused  # noqa: F401  (import local evita ciclo em alguns ambientes)

    harness = NonBashPermissionHarness()
    queue = AgentQueue(harness)
    system = create_system(nonbash_editor, "NonBash", "dispatch-nonbash")
    run = queue.enqueue(system.id, nonbash_editor.id, "explore o sistema", chat_session_id=None)

    deadline = time.time() + 5.0
    while time.time() < deadline and run.id not in queue.pending_gates:
        time.sleep(0.05)
    info = queue.pending_gates.get(run.id)
    assert info is not None
    assert info["sql"] is None
    assert info["permission"] == "external_directory"

    ok = queue.decide_gate(run.id, "per_ext_1", approve=True, user=nonbash_editor)
    assert ok is True
    assert harness.replied == [("per_ext_1", True)]

    from appaiforge import gate as gate_service

    # não gera entrada no histórico do gate de SQL (não é uma decisão de banco)
    assert gate_service.list_decisions(system.id) == []
