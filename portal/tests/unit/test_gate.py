"""Unitários do serviço do gate: decisão automática, auditoria e histórico (task 1.2)."""

import pytest

from appaiforge import auth, gate
from appaiforge.db import session_scope
from appaiforge.models import AgentRun, GateDecision, RunStatus, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def gate_system(clean_db):
    editor = auth.create_user("gate@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Gate", "gate-svc")


def test_bloqueada_e_recusada_automaticamente_com_registro (gate_system):
    decision = gate.evaluate(gate_system.id, "TRUNCATE TABLE clientes", origin="agente", connection_name="vendas")
    assert decision is gate.GateClass.BLOCKED
    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "bloqueada"
    assert history[0]["classification"] == "bloqueada"
    assert "TRUNCATE" in history[0]["sql"]


def test_normal_e_aprovada_automaticamente (gate_system):
    gate.evaluate(gate_system.id, "DELETE FROM clientes WHERE id = 3", origin="agente", connection_name="vendas")
    history = gate.list_decisions(gate_system.id)
    assert history[0]["decision"] == "aprovada"


def test_confirmavel_nao_gera_registro_ate_decisao (gate_system):
    result = gate.evaluate(gate_system.id, "DELETE FROM clientes", origin="agente", connection_name="vendas")
    assert result is gate.GateClass.CONFIRMABLE
    assert gate.list_decisions(gate_system.id) == []

    editor = auth.create_user("gate2@t.local", "pw", UserType.editor.value)
    gate.record_decision(
        gate_system.id, "DELETE FROM clientes", origin="agente", connection_name="vendas",
        classification=gate.GateClass.CONFIRMABLE, decision="aprovada", author_id=editor.id,
    )
    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "aprovada"
    assert history[0]["author_id"] == editor.id


def test_historico_ordena_e_limita (gate_system):
    for i in range(5):
        gate.evaluate(gate_system.id, f"DELETE FROM clientes WHERE id = {i}", origin="agente")
    assert len(gate.list_decisions(gate_system.id, limit=3)) == 3


# ---------- modo sombra (task 6.1) ----------

def test_record_shadow_decision_audita_confirmavel_sem_pendencia(gate_system):
    gate_class = gate.record_shadow_decision(gate_system.id, "DELETE FROM clientes", origin="agente")
    assert gate_class is gate.GateClass.CONFIRMABLE

    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "sombra"
    assert history[0]["classification"] == "confirmavel"


def test_record_shadow_decision_audita_bloqueada_sem_recusar_nada(gate_system):
    gate_class = gate.record_shadow_decision(gate_system.id, "DROP TABLE clientes", origin="agente")
    assert gate_class is gate.GateClass.BLOCKED
    history = gate.list_decisions(gate_system.id)
    assert history[0]["decision"] == "sombra"
    assert history[0]["classification"] == "bloqueada"


def test_record_shadow_decision_enforced_audita_como_bloqueada_nao_sombra(gate_system):
    """Fechamento de lacuna (roteiro de teste manual): o proxy já recusou
    de verdade em modo enforce — a auditoria precisa refletir isso, não
    "sombra" (que soa como "não aconteceu nada")."""
    gate_class = gate.record_shadow_decision(gate_system.id, "DROP TABLE clientes", origin="agente", enforced=True)
    assert gate_class is gate.GateClass.BLOCKED
    history = gate.list_decisions(gate_system.id)
    assert history[0]["decision"] == "bloqueada"
    assert history[0]["classification"] == "bloqueada"


def test_record_shadow_decision_reclassifica_no_servidor_nao_confia_no_chamador(gate_system):
    """O proxy não manda classificação nenhuma — só o SQL. O servidor
    reclassifica com o canônico, única fonte de verdade."""
    gate_class = gate.record_shadow_decision(gate_system.id, "SELECT 1", origin="agente")
    assert gate_class is gate.GateClass.NORMAL
    history = gate.list_decisions(gate_system.id)
    assert history[0]["classification"] == "normal"
    assert history[0]["decision"] == "sombra"


def test_record_shadow_decision_enforced_notifica_o_chat_da_run_ativa(gate_system):
    """Pedido do operador (task 7.3): bloqueio de DDL em enforce precisa
    aparecer no chat, não só na auditoria silenciosa — reaproveita o
    RunEvent `gate_denied` do caminho antigo, com a query bloqueada no
    texto."""
    from appaiforge.agent_queue import RunBuffer, get_queue

    editor = auth.create_user("notif-run@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    buffer = RunBuffer()
    get_queue().buffers[run_id] = buffer
    try:
        gate.record_shadow_decision(gate_system.id, "DROP TABLE clientes", origin="agente", enforced=True)
        eventos = buffer.snapshot()
        assert len(eventos) == 1
        assert eventos[0].kind == "gate_denied"
        assert "DROP TABLE clientes" in eventos[0].text
    finally:
        get_queue().buffers.pop(run_id, None)


def test_record_shadow_decision_enforced_confirmavel_tambem_notifica_com_motivo(gate_system):
    """A mudança que fecha o fluxo de aprovação (task 7.4): confirmável em
    enforce agora é recusada direto, igual à bloqueada — e precisa deixar o
    mesmo rastro visível no chat, com o motivo (sem WHERE) à mostra."""
    from appaiforge.agent_queue import RunBuffer, get_queue

    editor = auth.create_user("notif-confirmavel@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    buffer = RunBuffer()
    get_queue().buffers[run_id] = buffer
    try:
        gate_class = gate.record_shadow_decision(gate_system.id, "DELETE FROM clientes", origin="agente", enforced=True)
        assert gate_class is gate.GateClass.CONFIRMABLE
        eventos = buffer.snapshot()
        assert len(eventos) == 1
        assert eventos[0].kind == "gate_denied"
        assert "DELETE FROM clientes" in eventos[0].text
        assert "sem WHERE" in eventos[0].text
    finally:
        get_queue().buffers.pop(run_id, None)


def test_record_shadow_decision_sombra_nao_notifica_o_chat(gate_system):
    """Sombra nunca segura nem bloqueia de verdade — nada a avisar no chat,
    só a auditoria silenciosa de sempre."""
    from appaiforge.agent_queue import RunBuffer, get_queue

    editor = auth.create_user("notif-sombra@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    buffer = RunBuffer()
    get_queue().buffers[run_id] = buffer
    try:
        gate.record_shadow_decision(gate_system.id, "DROP TABLE clientes", origin="agente", enforced=False)
        assert buffer.snapshot() == []
    finally:
        get_queue().buffers.pop(run_id, None)


def test_record_shadow_decision_enforced_sem_buffer_nao_quebra(gate_system):
    """Melhor esforço: se a run já terminou e o buffer já foi descartado
    (ou nunca existiu, origem "app"), não há o que notificar ao vivo — só
    não pode derrubar a chamada; a auditoria em GateDecision já aconteceu
    de qualquer forma."""
    gate.record_shadow_decision(gate_system.id, "DROP TABLE clientes", origin="app", enforced=True)
    history = gate.list_decisions(gate_system.id)
    assert history[0]["decision"] == "bloqueada"


def test_record_shadow_decision_associa_ao_run_ativo_so_para_origem_agente(gate_system):
    editor = auth.create_user("sombra-run@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    gate.record_shadow_decision(gate_system.id, "DELETE FROM clientes", origin="agente")
    gate.record_shadow_decision(gate_system.id, "DELETE FROM pedidos", origin="app")

    with session_scope() as s:
        rows = {
            r.sql: r.run_id
            for r in s.query(GateDecision).filter_by(system_id=gate_system.id).all()
        }
    assert rows["DELETE FROM clientes"] == run_id  # origem agente: associa ao run ativo
    assert rows["DELETE FROM pedidos"] is None  # origem app: nunca associa run


def test_record_shadow_decision_emite_span_db_query_so_quando_ha_run_ativo(gate_system, finished_spans):
    """capability agent-telemetry: `db.query` correlacionado ao run_id em
    curso quando há um, e nenhum span de execução quando não há (requisitos
    "Consulta durante execução ativa" / "Consulta sem execução em curso")."""
    from appaiforge import telemetry

    editor = auth.create_user("sombra-span@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    gate.record_shadow_decision(gate_system.id, "DELETE FROM clientes", origin="agente")
    gate.record_shadow_decision(gate_system.id, "DELETE FROM pedidos", origin="app")

    spans = [s for s in finished_spans.get_finished_spans() if s.name == "db.query"]
    assert len(spans) == 1  # a de origem "app" (sem run ativo) não gera span
    assert spans[0].context.trace_id == telemetry.run_trace_id(run_id)
    assert spans[0].parent.span_id == telemetry.run_root_span_id(run_id)
