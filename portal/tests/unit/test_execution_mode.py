"""Unitários do modo de execução do container por sistema (tasks 4.1/4.3 da
etapa 1; tasks 5.1/5.2 da etapa 2 — decisão de sandboxed/reduced na criação)."""

import pytest

from appaiforge import auth, provisioning
from appaiforge.db import session_scope
from appaiforge.models import ExecutionMode, System, UserType
from appaiforge.services.systems import SlugTaken, create_system, get_system


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("exec-mode@t.local", "pw", UserType.editor.value)


def test_sistema_novo_nasce_sandboxed_quando_host_suporta_landlock(editor, monkeypatch):
    monkeypatch.setattr(provisioning, "landlock_abi", lambda: 8)
    system = create_system(editor, "Novo", "exec-novo")
    assert system.execution_mode == ExecutionMode.sandboxed
    assert get_system(system.id).execution_mode == ExecutionMode.sandboxed
    assert system.status_message == ""


def test_sistema_novo_nasce_reduced_com_aviso_quando_sem_landlock_e_require_sandbox_desligado(
    editor, monkeypatch
):
    monkeypatch.setattr(provisioning, "landlock_abi", lambda: 0)
    fake_settings = type("S", (), {"require_sandbox": False})()
    monkeypatch.setattr(provisioning, "get_settings", lambda: fake_settings)

    system = create_system(editor, "Degradado", "exec-degradado")

    assert system.execution_mode == ExecutionMode.reduced
    assert "reduced" in system.status_message
    assert "Landlock" in system.status_message


def test_criacao_falha_quando_sem_landlock_e_require_sandbox_ligado(editor, monkeypatch):
    monkeypatch.setattr(provisioning, "landlock_abi", lambda: 0)
    fake_settings = type("S", (), {"require_sandbox": True})()
    monkeypatch.setattr(provisioning, "get_settings", lambda: fake_settings)

    with pytest.raises(provisioning.SandboxUnavailable):
        create_system(editor, "Falha", "exec-falha-sandbox")

    # a linha não deve ter sido criada — o slug continua livre, mesmo depois
    # que o host volta a suportar o confinamento
    monkeypatch.setattr(provisioning, "landlock_abi", lambda: 8)
    outro = create_system(editor, "Depois", "exec-falha-sandbox")
    assert outro.slug == "exec-falha-sandbox"


def test_modo_e_consultavel_e_distingue_sistemas(editor, monkeypatch):
    """Scenario 'Modo visível para o admin': o modo de cada sistema é consultável,
    permitindo distinguir quem ainda roda no modo antigo (sem migração automática)."""
    monkeypatch.setattr(provisioning, "landlock_abi", lambda: 8)
    novo = create_system(editor, "Novo", "exec-novo-2")
    antigo = create_system(editor, "Antigo", "exec-antigo")
    with session_scope() as s:
        row = s.get(System, antigo.id)
        row.execution_mode = ExecutionMode.legacy

    assert get_system(novo.id).execution_mode == ExecutionMode.sandboxed
    assert get_system(antigo.id).execution_mode == ExecutionMode.legacy
