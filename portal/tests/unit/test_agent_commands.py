"""Lista de comandos do agente para o autocomplete (change add-openspec-to-system-container, 4.2)."""

import pytest

from appaiforge.harness.fake import FakeHarness
from appaiforge.services import agent_commands


def test_fake_le_comandos_do_workspace_com_descricao(tmp_path):
    cmds = tmp_path / "erp" / ".opencode" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "opsx-propose.md").write_text('---\ndescription: "Propose a new change"\n---\n\ncorpo\n')
    (cmds / "opsx-apply.md").write_text("---\ndescription: Implement tasks\n---\n")
    (cmds / "LEIAME.txt").write_text("ignorado")
    harness = FakeHarness(str(tmp_path), step_delay=0)
    assert harness.list_commands({"slug": "erp"}) == [
        {"name": "opsx-apply", "description": "Implement tasks"},
        {"name": "opsx-propose", "description": "Propose a new change"},
    ]
    assert harness.list_commands({"slug": "sem-workspace"}) == []


class _Harness:
    def __init__(self):
        self.calls = 0
        self.result: object = [{"name": "opsx-propose", "description": "d"}]

    def list_commands(self, system):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Queue:
    def __init__(self, harness):
        self.h = harness

    def harness_for(self, system):
        return self.h


@pytest.fixture()
def harness(monkeypatch):
    h = _Harness()
    import appaiforge.agent_queue as aq

    monkeypatch.setattr(aq, "get_queue", lambda: _Queue(h))
    agent_commands.invalidate()
    yield h
    agent_commands.invalidate()


SYSTEM = {"id": "s1", "slug": "erp", "agent_profile": None}


def test_cache_por_sistema_e_invalidacao(harness):
    assert agent_commands.list_for(SYSTEM) == [{"name": "opsx-propose", "description": "d"}]
    agent_commands.list_for(SYSTEM)
    assert harness.calls == 1
    agent_commands.invalidate("s1")
    agent_commands.list_for(SYSTEM)
    assert harness.calls == 2


def test_cache_expira(harness, monkeypatch):
    agent_commands.list_for(SYSTEM)
    now = agent_commands.time.monotonic()
    monkeypatch.setattr(agent_commands.time, "monotonic", lambda: now + agent_commands.TTL_SECONDS + 1)
    agent_commands.list_for(SYSTEM)
    assert harness.calls == 2


def test_falha_do_harness_vira_lista_vazia_com_cache_curto(harness, monkeypatch):
    harness.result = RuntimeError("agente fora do ar")
    assert agent_commands.list_for(SYSTEM) == []
    now = agent_commands.time.monotonic()
    monkeypatch.setattr(agent_commands.time, "monotonic", lambda: now + agent_commands.EMPTY_TTL_SECONDS + 1)
    harness.result = [{"name": "opsx-apply", "description": ""}]
    assert agent_commands.list_for(SYSTEM) == [{"name": "opsx-apply", "description": ""}]
