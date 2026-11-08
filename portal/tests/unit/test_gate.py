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


# ---------- pedidos de aprovação do proxy de banco (task 4.1) ----------

def test_create_request_fica_pendente_com_prazo(gate_system):
    req = gate.create_request(
        gate_system.id, "DELETE FROM clientes", origin="agente",
        connection_name="vendas", reason="sem WHERE", timeout_seconds=60,
    )
    assert req["status"] == gate.GateRequestStatus.PENDING.value
    assert req["sql"] == "DELETE FROM clientes"
    assert req["decided_at"] is None
    assert req["expires_at"] > req["created_at"]


def test_get_request_desconhecido_e_none(gate_system):
    assert gate.get_request("nao-existe") is None


def test_decide_request_aprovada_libera_e_audita(gate_system):
    editor = auth.create_user("aprova@t.local", "pw", UserType.editor.value)
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=60)

    decided = gate.decide_request(req["id"], approve=True, author_id=editor.id, author_email=editor.email)
    assert decided["status"] == gate.GateRequestStatus.APPROVED.value
    assert decided["decided_at"] is not None

    fetched = gate.get_request(req["id"])
    assert fetched["status"] == gate.GateRequestStatus.APPROVED.value

    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "aprovada"
    assert history[0]["author_id"] == editor.id


def test_decide_request_recusada_nao_libera(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="app", timeout_seconds=60)
    decided = gate.decide_request(req["id"], approve=False)
    assert decided["status"] == gate.GateRequestStatus.REJECTED.value
    history = gate.list_decisions(gate_system.id)
    assert history[0]["decision"] == "recusada"
    assert history[0]["origin"] == "app"


def test_decide_request_e_idempotente_nao_sobrescreve(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=60)
    gate.decide_request(req["id"], approve=True)
    segunda = gate.decide_request(req["id"], approve=False)
    assert segunda["status"] == gate.GateRequestStatus.APPROVED.value  # a primeira decisão vale
    assert len(gate.list_decisions(gate_system.id)) == 1


def test_get_request_expira_sozinho_apos_o_prazo(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)
    fetched = gate.get_request(req["id"])
    assert fetched["status"] == gate.GateRequestStatus.EXPIRED.value
    assert fetched["decided_at"] is not None


def test_decide_request_apos_expirar_nao_aprova(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)
    decided = gate.decide_request(req["id"], approve=True)
    assert decided["status"] == gate.GateRequestStatus.EXPIRED.value
    # a expiração em si fica auditada (decision="expirada") — achado do roteiro de
    # teste manual: antes dessa correção, nem bloqueada nem expirada apareciam
    # em GateDecision, só aprovada/recusada por decisão humana.
    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "expirada"
    assert history[0]["classification"] == "confirmavel"


def test_get_request_expirando_sozinho_tambem_audita(gate_system):
    """A expiração detectada pelo poll do proxy (get_request), não só pela
    decide_request tardia, também precisa gerar o registro."""
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)
    gate.get_request(req["id"])
    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "expirada"


def test_expiracao_e_auditada_uma_unica_vez_mesmo_com_consultas_repetidas(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)
    gate.get_request(req["id"])
    gate.get_request(req["id"])
    gate.decide_request(req["id"], approve=True)
    assert len(gate.list_decisions(gate_system.id)) == 1


def test_list_pending_for_run_expirando_tambem_audita(gate_system):
    editor = auth.create_user("expira-lista@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.awaiting_approval, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)
    gate.list_pending_for_run(run_id)
    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "expirada"


# ---------- associação ao run ativo e listagem pro chat (task 4.2) ----------

def test_create_request_de_origem_agente_associa_ao_run_ativo(gate_system):
    editor = auth.create_user("run-ativo@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.awaiting_approval, prompt="apague os clientes inativos",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente")
    assert req["run_id"] == run_id


def test_create_request_sem_run_ativo_fica_sem_run_id(gate_system):
    req = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente")
    assert req["run_id"] is None


def test_create_request_de_origem_app_nunca_associa_run():
    """A app gerada não é uma execução do agente — mesmo com um run ativo no
    sistema, a origem `app` não deve carregar essa atribuição."""
    editor = auth.create_user("app-origin@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Gate App", "gate-app-origin")
    with session_scope() as s:
        run = AgentRun(
            system_id=system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="algo",
        )
        s.add(run)

    req = gate.create_request(system.id, "DELETE FROM pedidos", origin="app")
    assert req["run_id"] is None


def test_list_pending_for_run_mostra_so_as_pendentes_do_run(gate_system):
    editor = auth.create_user("list-run@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.awaiting_approval, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    req1 = gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente")
    req2 = gate.create_request(gate_system.id, "DELETE FROM pedidos", origin="agente")
    gate.decide_request(req2["id"], approve=True)  # decidida: não deve aparecer na lista

    pending = gate.list_pending_for_run(run_id)
    assert [p["id"] for p in pending] == [req1["id"]]


def test_list_pending_for_run_expira_e_some_da_lista(gate_system):
    editor = auth.create_user("list-expira@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=gate_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.awaiting_approval, prompt="p",
        )
        s.add(run)
        s.flush()
        run_id = run.id

    gate.create_request(gate_system.id, "DELETE FROM clientes", origin="agente", timeout_seconds=0)
    import time
    time.sleep(0.01)

    assert gate.list_pending_for_run(run_id) == []


# ---------- modo sombra (task 6.1) ----------

def test_record_shadow_decision_audita_confirmavel_sem_pendencia(gate_system):
    gate_class = gate.record_shadow_decision(gate_system.id, "DELETE FROM clientes", origin="agente")
    assert gate_class is gate.GateClass.CONFIRMABLE

    history = gate.list_decisions(gate_system.id)
    assert len(history) == 1
    assert history[0]["decision"] == "sombra"
    assert history[0]["classification"] == "confirmavel"
    # sombra não cria pendência nenhuma — nada a aprovar/recusar
    assert gate.list_pending_for_run(gate_system.id) == []


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
