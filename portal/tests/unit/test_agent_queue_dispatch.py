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


class InterleavedQuietHarness(HarnessPort):
    """Achado ao vivo (critique do Chat): dois `command_run` idênticos com um
    `tool_output` (kind silencioso no chat, _QUIET_KINDS) entre eles — o
    dedup antigo só lembrava do ÚLTIMO evento despachado, de qualquer kind,
    então o `tool_output` no meio "zerava" a memória e o segundo
    `command_run` igual passava, duplicado, no log (o `tool_output` em si
    nunca aparece na tela, então os dois `command_run` pareciam consecutivos
    e idênticos pro usuário)."""

    def create_session(self, system: dict) -> str:
        return "ses_interleaved"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("command_run", text="total 0", meta={"command": "ls -la"}))
        on_event(RunEvent("tool_output", text="total 0", meta={"tool": "bash"}))
        on_event(RunEvent("command_run", text="total 0", meta={"command": "ls -la"}))  # mesmo comando reemitido
        on_event(RunEvent("run_finished"))


def test_dedup_nao_e_quebrado_por_evento_silencioso_no_meio(editor, fake_workspace):
    harness = InterleavedQuietHarness()
    queue = AgentQueue(harness)
    system = create_system(editor, "Dispatch3", "dispatch-interleaved")
    run = queue.enqueue(system.id, editor.id, "faça algo", chat_session_id=None)
    _wait_run(queue, run.id)

    events = queue.buffers[run.id].snapshot()
    command_runs = [e for e in events if e.kind == "command_run"]
    assert len(command_runs) == 1


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


class QuestionHarness(HarnessPort):
    """Simula o agente usando a ferramenta nativa `question` do opencode por
    conta própria (achado ao vivo: pediu confirmação de um DELETE sem WHERE
    sem nenhum gate envolvido) — distinta do pedido de permissão acima."""

    def __init__(self):
        self.replied: list[tuple[str, str]] = []
        self.rejected: list[str] = []

    def create_session(self, system: dict) -> str:
        return "ses_question"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        pass

    def reply_question(self, system: dict, session_id: str, request_id: str, label: str) -> None:
        self.replied.append((request_id, label))

    def reject_question(self, system: dict, session_id: str, request_id: str) -> None:
        self.rejected.append(request_id)

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started"))
        on_event(RunEvent("question_asked", text="Confirma apagar tudo?", meta={
            "request_id": "que_1", "header": "Confirmar DELETE",
            "options": ["Sim, apagar", "Cancelar"],
        }))
        # a run fica presa aguardando decide_question(); o teste decide e segue


@pytest.fixture()
def question_editor(clean_db):
    return auth.create_user("question@t.local", "pw", UserType.editor.value)


def test_pergunta_do_agente_fica_pendente_ate_decisao_e_nao_gera_gate_decision(question_editor, fake_workspace):
    """A run fica presa até alguém responder — sem isto, uma pergunta que o
    próprio modelo faz (não o gate) deixava a execução travada pra sempre."""
    harness = QuestionHarness()
    queue = AgentQueue(harness)
    system = create_system(question_editor, "Question", "dispatch-question")
    run = queue.enqueue(system.id, question_editor.id, "fazer delete sem where", chat_session_id=None)

    deadline = time.time() + 5.0
    while time.time() < deadline and run.id not in queue.pending_questions:
        time.sleep(0.05)
    info = queue.pending_questions.get(run.id)
    assert info is not None
    assert info["question"] == "Confirma apagar tudo?"
    assert info["options"] == ["Sim, apagar", "Cancelar"]

    ok = queue.decide_question(run.id, "que_1", "Sim, apagar")
    assert ok is True
    assert harness.replied == [("que_1", "Sim, apagar")]
    assert run.id not in queue.pending_questions

    from appaiforge import gate as gate_service

    # não é uma decisão do gate de SQL — não entra no histórico de destrutivas
    assert gate_service.list_decisions(system.id) == []


class _OtherHarness(HarnessPort):
    def create_session(self, system: dict) -> str:
        return "ses_other"

    def interrupt(self, system: dict, session_id: str) -> None:
        pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        pass


def test_harness_for_usa_injetado_no_construtor_para_o_protocolo_padrao():
    """change generalize-agent-runtime-plumbing: harness_for não deve
    ignorar o harness injetado no construtor (é assim que esta suíte toda
    injeta harnesses de teste) para o protocolo do perfil padrão."""
    harness = ScriptedHarness()
    queue = AgentQueue(harness)
    assert queue.harness_for({"agent_profile": "opencode"}) is harness
    assert queue.harness_for({}) is harness  # sem perfil -> perfil padrão


def test_harness_for_despacha_protocolo_diferente_via_registro(monkeypatch):
    """Um perfil com harness_protocol diferente do padrão é resolvido via
    HARNESS_IMPLEMENTATIONS, não pelo harness injetado no construtor -
    o ponto de extensão que a etapa 7 do roadmap vai usar."""
    import appaiforge.agent_queue as agent_queue_module
    from appaiforge.agent_profiles import PROFILES

    monkeypatch.setitem(PROFILES, "outro-agente", {**PROFILES["opencode"], "harness_protocol": "outro-protocolo"})
    other = _OtherHarness()
    monkeypatch.setitem(agent_queue_module.HARNESS_IMPLEMENTATIONS, "outro-protocolo", lambda: other)

    harness = ScriptedHarness()
    queue = AgentQueue(harness)
    resolved = queue.harness_for({"agent_profile": "outro-agente"})
    assert resolved is other
    assert resolved is not harness
    # chamada repetida devolve a mesma instância (cache por protocolo)
    assert queue.harness_for({"agent_profile": "outro-agente"}) is other


def test_interromper_run_com_pergunta_pendente_rejeita_sem_resposta(question_editor, fake_workspace):
    harness = QuestionHarness()
    queue = AgentQueue(harness)
    system = create_system(question_editor, "Question2", "dispatch-question-interrupt")
    run = queue.enqueue(system.id, question_editor.id, "fazer delete sem where", chat_session_id=None)

    deadline = time.time() + 5.0
    while time.time() < deadline and run.id not in queue.pending_questions:
        time.sleep(0.05)
    assert run.id in queue.pending_questions

    queue.interrupt(run.id, system)
    assert harness.rejected == ["que_1"]
    assert run.id not in queue.pending_questions
