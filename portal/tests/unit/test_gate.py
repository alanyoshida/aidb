"""Unitários do serviço do gate: decisão automática, auditoria e histórico (task 1.2)."""

import pytest

from appaiforge import auth, gate
from appaiforge.models import UserType
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
