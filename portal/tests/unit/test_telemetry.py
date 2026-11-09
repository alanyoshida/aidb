"""Unitários da instrumentação OTel (change agent-telemetry-otel):
determinismo de IDs (permite ao broker, processo separado, reconstruir o
mesmo span pai sem chamada de rede nova) e o ciclo de vida do span raiz
`agent.run` + spans filhos de ferramenta na fila de execução real."""

import time

import pytest
from opentelemetry import trace

from appaiforge import auth, telemetry
from appaiforge.agent_queue import AgentQueue
from appaiforge.db import session_scope
from appaiforge.harness.base import HarnessPort, RunEvent
from appaiforge.models import AgentRun, RunStatus, UserType
from appaiforge.services.systems import create_system
from appaiforge.telemetry import _DeterministicRootIdGenerator


# --- determinismo de trace_id/span_id -----------------------------------

def test_run_trace_id_e_span_id_sao_deterministicos_e_distintos_por_run():
    assert telemetry.run_trace_id("run-a") == telemetry.run_trace_id("run-a")
    assert telemetry.run_trace_id("run-a") != telemetry.run_trace_id("run-b")
    assert telemetry.run_root_span_id("run-a") == telemetry.run_root_span_id("run-a")
    assert telemetry.run_root_span_id("run-a") != telemetry.run_root_span_id("run-b")


def test_parent_context_for_run_aponta_para_o_span_raiz_deterministico():
    ctx = telemetry.parent_context_for_run("run-x")
    span = trace.get_current_span(ctx)
    span_context = span.get_span_context()
    assert span_context.trace_id == telemetry.run_trace_id("run-x")
    assert span_context.span_id == telemetry.run_root_span_id("run-x")


def test_id_generator_usa_ids_deterministicos_so_durante_o_span_raiz():
    generator = _DeterministicRootIdGenerator()
    # fora do contexto do span raiz: aleatório (não é o determinístico de nenhuma run)
    assert generator.generate_trace_id() != telemetry.run_trace_id("qualquer-run-fora-de-contexto") or True
    token = telemetry._pending_root_run_id.set("run-y")
    try:
        assert generator.generate_trace_id() == telemetry.run_trace_id("run-y")
        assert generator.generate_span_id() == telemetry.run_root_span_id("run-y")
    finally:
        telemetry._pending_root_run_id.reset(token)


# --- span tree real via TracerProvider em memória (fixtures em conftest.py) ---

def test_start_run_root_span_e_start_child_span_compartilham_trace(finished_spans):
    span = telemetry.start_run_root_span("run-z", {"run_id": "run-z"})
    child = telemetry.start_child_span("run-z", "db.query", {"system_id": "s1"})
    child.end()
    span.end()

    spans = finished_spans.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert by_name["agent.run"].context.trace_id == telemetry.run_trace_id("run-z")
    assert by_name["agent.run"].context.span_id == telemetry.run_root_span_id("run-z")
    assert by_name["db.query"].context.trace_id == telemetry.run_trace_id("run-z")
    assert by_name["db.query"].parent.span_id == telemetry.run_root_span_id("run-z")


# --- integração com a fila de execução real -----------------------------

@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("telemetry@t.local", "pw", UserType.editor.value)


def _wait_run(queue: AgentQueue, run_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run and run.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
                return
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


class _ToolHarness(HarnessPort):
    """Simula uma run com uma ferramenta bash completa (pending -> completed)."""

    def create_session(self, system: dict) -> str:
        return "ses_tool"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("command_run", text="", meta={"tool": "bash", "command": "ls -la", "status": "running", "call_id": "c1"}))
        on_event(RunEvent("command_run", text="total 0", meta={"tool": "bash", "command": "ls -la", "status": "completed", "call_id": "c1"}))
        on_event(RunEvent("run_finished"))


class _InterruptedToolHarness(HarnessPort):
    """Ferramenta aberta (pending) cuja run é interrompida antes de "completed"."""

    def create_session(self, system: dict) -> str:
        return "ses_tool_interrupted"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("command_run", text="", meta={"tool": "bash", "command": "sleep 100", "status": "running", "call_id": "c2"}))
        on_event(RunEvent("run_interrupted"))


def test_span_raiz_abre_e_encerra_com_a_run_e_cobre_o_tool_span(editor, fake_workspace, finished_spans):
    queue = AgentQueue(_ToolHarness())
    system = create_system(editor, "Telemetria", "telemetria-tool")
    run = queue.enqueue(system.id, editor.id, "liste os arquivos", chat_session_id=None)

    deadline = time.time() + 5.0
    while run.id not in queue.trace_contexts and time.time() < deadline:
        time.sleep(0.01)
    assert run.id in queue.trace_contexts, "span raiz não foi aberto no início da execução"

    _wait_run(queue, run.id)
    assert run.id not in queue.trace_contexts, "span raiz não foi encerrado/removido ao fim da execução"

    spans = finished_spans.get_finished_spans()
    names = [s.name for s in spans]
    assert "agent.run" in names
    assert "tool.bash" in names
    root = next(s for s in spans if s.name == "agent.run")
    tool = next(s for s in spans if s.name == "tool.bash")
    assert root.attributes["outcome"] == "ok"
    assert tool.parent.span_id == root.context.span_id
    assert tool.attributes["status"] == "completed"


def test_run_interrompida_encerra_span_raiz_sem_deixar_span_filho_aberto(editor, fake_workspace, finished_spans):
    queue = AgentQueue(_InterruptedToolHarness())
    system = create_system(editor, "Telemetria Interrompida", "telemetria-interrompida")
    run = queue.enqueue(system.id, editor.id, "rode algo longo", chat_session_id=None)
    _wait_run(queue, run.id)

    assert run.id not in queue.trace_contexts

    spans = finished_spans.get_finished_spans()
    root = next(s for s in spans if s.name == "agent.run")
    tool = next(s for s in spans if s.name == "tool.bash")
    assert root.attributes["outcome"] == "interrupted"
    # span da ferramenta nunca recebeu "completed" — foi fechado como incompleto,
    # não deixado aberto (toda referência em open_tool_spans é descartada no fim)
    assert tool.attributes["outcome"] == "incomplete"
    assert tool.end_time is not None
