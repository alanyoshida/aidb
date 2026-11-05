"""Unitários do modo de execução do container por sistema (tasks 4.1/4.3)."""

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import ExecutionMode, System, UserType
from appaiforge.services.systems import create_system, get_system


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("exec-mode@t.local", "pw", UserType.editor.value)


def test_sistema_novo_nasce_no_modo_reduzido(editor):
    system = create_system(editor, "Novo", "exec-novo")
    assert system.execution_mode == ExecutionMode.reduced
    assert get_system(system.id).execution_mode == ExecutionMode.reduced


def test_modo_e_consultavel_e_distingue_sistemas(editor):
    """Scenario 'Modo visível para o admin': o modo de cada sistema é consultável,
    permitindo distinguir quem ainda roda no modo antigo (sem migração automática)."""
    novo = create_system(editor, "Novo", "exec-novo-2")
    antigo = create_system(editor, "Antigo", "exec-antigo")
    with session_scope() as s:
        row = s.get(System, antigo.id)
        row.execution_mode = ExecutionMode.legacy

    assert get_system(novo.id).execution_mode == ExecutionMode.reduced
    assert get_system(antigo.id).execution_mode == ExecutionMode.legacy
