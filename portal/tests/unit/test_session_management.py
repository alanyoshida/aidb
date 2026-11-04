"""Unitários: gerenciamento de sessão opencode (reuso, context_reset, invalidação)."""

import threading
import time

import pytest

from appaiforge import auth
from appaiforge.agent_queue import AgentQueue, RunBuffer
from appaiforge.db import session_scope
from appaiforge.harness.base import HarnessPort, RunEvent
from appaiforge.models import ChatSession, RunStatus, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


class TrackingHarness(HarnessPort):
    """Harness que registra chamadas a create_session para asserção."""

    def __init__(self):
        self.create_calls: list[str] = []  # session_ids criados
        self._counter = 0

    def create_session(self, system: dict) -> str:
        self._counter += 1
        sid = f"new-session-{self._counter}"
        self.create_calls.append(sid)
        return sid

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("message", text=f"resposta para: {prompt}"))
        on_event(RunEvent("run_finished", meta={"summary": prompt}))


def _wait_run(queue: AgentQueue, run_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            from appaiforge.models import AgentRun
            run = s.get(AgentRun, run_id)
            if run and run.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
                return
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


def test_execute_reutiliza_session_id_existente(clean_db, fake_workspace):
    """_execute() não chama create_session() quando ChatSession já tem harness_session_id."""
    editor = auth.create_user("sess-reuse@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Reuse", "reuse")

    # Pré-cria uma ChatSession com harness_session_id já salvo
    with session_scope() as s:
        cs = ChatSession(
            system_id=system.id,
            user_id=editor.id,
            title="existente",
            harness_session_id="pre-existing-session",
            context_reset=False,
        )
        s.add(cs)
        s.flush()
        chat_id = cs.id

    harness = TrackingHarness()
    queue = AgentQueue(harness)
    run = queue.enqueue(system.id, editor.id, "olá", chat_session_id=chat_id)
    _wait_run(queue, run.id)

    assert harness.create_calls == [], (
        "create_session() não deve ser chamado quando harness_session_id já existe"
    )


def test_execute_emite_context_reset_quando_context_reset_true(clean_db, fake_workspace):
    """_execute() emite session_context_reset e cria nova sessão quando context_reset=True."""
    editor = auth.create_user("sess-reset@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Reset", "reset")

    # ChatSession com context_reset=True (container foi recriado)
    with session_scope() as s:
        cs = ChatSession(
            system_id=system.id,
            user_id=editor.id,
            title="reset-session",
            harness_session_id="old-session",
            context_reset=True,
        )
        s.add(cs)
        s.flush()
        chat_id = cs.id

    harness = TrackingHarness()
    queue = AgentQueue(harness)
    run = queue.enqueue(system.id, editor.id, "novo contexto", chat_session_id=chat_id)
    _wait_run(queue, run.id)

    # create_session() deve ter sido chamado UMA vez
    assert len(harness.create_calls) == 1, "create_session() deve ser chamado uma vez após context_reset"

    # buffer deve conter session_context_reset
    buf = queue.buffers.get(run.id)
    assert buf is not None
    kinds = [e.kind for e in buf.snapshot()]
    assert "session_context_reset" in kinds, "evento session_context_reset deve estar no buffer"

    # context_reset deve ter sido limpo no banco
    with session_scope() as s:
        cs_after = s.get(ChatSession, chat_id)
        assert cs_after.context_reset is False
        assert cs_after.harness_session_id == harness.create_calls[0]


def test_provision_system_invalida_todas_as_sessions(clean_db, fake_workspace, monkeypatch):
    """provision_system() seta context_reset=True e zera harness_session_id para o sistema."""
    import docker

    editor = auth.create_user("provision@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Prov", "prov")

    # Cria duas ChatSessions com harness_session_id preenchido
    with session_scope() as s:
        for i in range(2):
            cs = ChatSession(
                system_id=system.id,
                user_id=editor.id,
                title=f"sessão-{i}",
                harness_session_id=f"sess-{i}",
                context_reset=False,
            )
            s.add(cs)

    # Mocka Docker para não precisar de daemon real
    class FakeContainer:
        id = "fake-container-id"

    class FakeContainers:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def run(self, **kwargs):
            return FakeContainer()

    class FakeClient:
        containers = FakeContainers()

        def networks(self):
            return self

        def get(self, name):
            return self

    monkeypatch.setattr("appaiforge.provisioning._docker", lambda: FakeClient())
    monkeypatch.setattr("appaiforge.provisioning.ensure_network", lambda: None)
    monkeypatch.setattr("appaiforge.provisioning.write_opencode_config", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.provisioning._provider_env", lambda *a: {})
    monkeypatch.setattr("appaiforge.provisioning._connection_env", lambda *a: {})
    monkeypatch.setattr("appaiforge.provisioning._check_capacity", lambda *a: None)
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(fake_workspace / "host"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(fake_workspace / "hconf"))
    from appaiforge.config import get_settings
    get_settings.cache_clear()

    from appaiforge.provisioning import provision_system
    provision_system(system)

    with session_scope() as s:
        sessions = s.execute(
            __import__("sqlalchemy").select(ChatSession).where(ChatSession.system_id == system.id)
        ).scalars().all()

    assert len(sessions) == 2
    for cs in sessions:
        assert cs.context_reset is True, f"sessão {cs.id}: context_reset deve ser True"
        assert cs.harness_session_id is None, f"sessão {cs.id}: harness_session_id deve ser None"
