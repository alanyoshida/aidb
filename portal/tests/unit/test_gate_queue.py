"""Unitários do gate na fila (tasks 2.4/2.5): bloqueio automático, aprovação e
recusa do editor, estado awaiting_approval e interrupção com pendência."""

import time

import pytest

from appaiforge import auth, gate
from appaiforge.agent_queue import AgentQueue
from appaiforge.harness.fake import FakeHarness
from appaiforge.models import RunStatus, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _queue(fake_env) -> AgentQueue:
    return AgentQueue(FakeHarness(str(fake_env / "workspaces"), step_delay=0))


def _wait_status(queue, run_id, statuses, timeout=15):
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun

    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            row = s.get(AgentRun, run_id)
            if row is not None and row.status in statuses:
                return row
        time.sleep(0.1)
    with session_scope() as s:
        return s.get(AgentRun, run_id)


def test_truncate_e_bloqueado_sem_intervencao(fake_env, clean_db):
    editor = auth.create_user("g1@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "G", "gate-trunc")
    queue = _queue(fake_env)
    run = queue.enqueue(system.id, editor.id, "por favor TRUNCATE a tabela")

    row = _wait_status(queue, run.id, {RunStatus.succeeded, RunStatus.failed})
    assert row.status == RunStatus.succeeded  # o agente é informado e encerra
    assert "recusada pelo gate" in (row.summary or "")
    decisions = gate.list_decisions(system.id)
    assert decisions and decisions[0]["decision"] == "bloqueada"
    assert run.id not in queue.pending_gates


def test_delete_em_massa_aguarda_e_e_aprovado_pelo_editor(fake_env, clean_db):
    editor = auth.create_user("g2@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "G", "gate-aprov")
    queue = _queue(fake_env)
    run = queue.enqueue(system.id, editor.id, "agora DELETE SEM WHERE na tabela")

    row = _wait_status(queue, run.id, {RunStatus.awaiting_approval})
    assert row.status == RunStatus.awaiting_approval
    assert run.id in queue.pending_gates
    request_id = queue.pending_gates[run.id]["request_id"]
    assert gate.list_decisions(system.id) == []  # confirmável: nada decidido ainda

    assert queue.decide_gate(run.id, request_id, approve=True, user=editor)
    row = _wait_status(queue, run.id, {RunStatus.succeeded, RunStatus.failed})
    assert row.status == RunStatus.succeeded
    assert "executada com aprovação" in (row.summary or "")
    decisions = gate.list_decisions(system.id)
    assert decisions[0]["decision"] == "aprovada"
    assert decisions[0]["author_id"] == editor.id


def test_recusa_do_editor_notifica_o_agente_e_audita(fake_env, clean_db):
    editor = auth.create_user("g3@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "G", "gate-recusa")
    queue = _queue(fake_env)
    run = queue.enqueue(system.id, editor.id, "agora DELETE SEM WHERE na tabela")

    row = _wait_status(queue, run.id, {RunStatus.awaiting_approval})
    request_id = queue.pending_gates[run.id]["request_id"]

    assert queue.decide_gate(run.id, request_id, approve=False, user=editor)
    row = _wait_status(queue, run.id, {RunStatus.succeeded, RunStatus.failed})
    assert "recusada pelo gate" in (row.summary or "")
    decisions = gate.list_decisions(system.id)
    assert decisions[0]["decision"] == "recusada"


def test_comando_sem_sql_identificavel_e_confirmavel(fake_env, clean_db):
    editor = auth.create_user("g4@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "G", "gate-unknown")
    queue = _queue(fake_env)

    from appaiforge.agent_queue import RunBuffer, RunEvent
    from appaiforge.harness.base import RunEvent as RE

    run_id = "run_manual"
    queue.buffers[run_id] = RunBuffer()
    queue._handle_gate_request(
        {"system_id": system.id, "slug": system.slug},
        run_id, editor.id,
        RE("gate_request", text="psql $DATABASE_URL_VENDAS", meta={"request_id": "per_x", "session_id": "s1"}),
        queue.buffers[run_id], "s1",
    )
    assert run_id in queue.pending_gates  # sem SQL identificável -> pergunta ao editor
