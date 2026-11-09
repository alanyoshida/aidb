"""Unitários de `services/telemetry_query.py` (change agent-telemetry-backend-agnostic):
sem nenhum span persistido pra uma run, `fetch_run_trace` devolve `None` (o
Debug log cai no comportamento atual); com spans persistidos, devolve a
árvore ordenada; qualquer falha ao consultar devolve `None`, sem propagar."""

from datetime import datetime, timedelta, timezone

import pytest

from appaiforge.services import telemetry_query


@pytest.fixture()
def run_with_spans(editor, clean_db):
    """Cria um AgentRun real e dois `AgentTelemetrySpan` associados a ele
    (raiz + filho), direto no banco - sem passar pela fila de execução real,
    já que aqui o alvo é só o caminho de leitura."""
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, AgentTelemetrySpan, RunStatus
    from appaiforge.services.systems import create_system

    system = create_system(editor, "Telemetria Query", "telemetria-query")
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        run = AgentRun(
            system_id=system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.succeeded, prompt="oi",
        )
        s.add(run)
        s.flush()
        run_id = run.id
        s.add_all([
            AgentTelemetrySpan(
                run_id=run_id, span_id="root1", parent_span_id=None, name="agent.run",
                start_time=now, end_time=now + timedelta(seconds=5),
                attributes={"run_id": run_id, "outcome": "ok"},
            ),
            AgentTelemetrySpan(
                run_id=run_id, span_id="child1", parent_span_id="root1", name="db.query",
                start_time=now + timedelta(seconds=1), end_time=now + timedelta(seconds=2),
                attributes={"run_id": run_id, "classification": "normal"},
            ),
        ])
    return run_id


def test_sem_spans_persistidos_devolve_none(editor, clean_db):
    assert telemetry_query.fetch_run_trace("run-sem-spans") is None


def test_consulta_retorna_arvore_ordenada(run_with_spans):
    spans = telemetry_query.fetch_run_trace(run_with_spans)

    assert spans is not None
    assert [s["name"] for s in spans] == ["agent.run", "db.query"]
    assert spans[1]["parent_span_id"] == "root1"
    assert spans[1]["attributes"]["classification"] == "normal"


def test_falha_ao_consultar_devolve_none_sem_propagar(monkeypatch, run_with_spans):
    import appaiforge.db as db_mod

    def _boom():
        raise RuntimeError("Postgres fora do ar")

    monkeypatch.setattr(db_mod, "session_scope", _boom)

    assert telemetry_query.fetch_run_trace(run_with_spans) is None
