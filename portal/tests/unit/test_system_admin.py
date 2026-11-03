"""Unitários de renomear sistema, editar provedor e mapa de modelos (tasks 3.1, 3.2)."""

import pytest

from appaiforge import auth
from appaiforge.config import KNOWN_MODELS, models_for
from appaiforge.models import UserType
from appaiforge.services import audit
from appaiforge.services.systems import NotPermitted, create_system, get_system, rename_system, set_provider


@pytest.fixture()
def owner_system(clean_db):
    editor = auth.create_user("owner@sys.local", "pw", UserType.editor.value)
    return editor, create_system(editor, "ERP", "erp-admin")


def test_rename_system_reflete_e_audita(owner_system):
    editor, system = owner_system
    rename_system(system, "ERP Novo", editor)
    assert get_system(system.id).name == "ERP Novo"
    entries = [e for e in audit.list_by_system(system.id) if e["action"] == "system.rename"]
    assert entries
    assert entries[0]["details"] == {"old": "ERP", "new": "ERP Novo"}
    assert entries[0]["actor_id"] == editor.id


def test_rename_system_mantem_slug(owner_system):
    editor, system = owner_system
    rename_system(system, "Outro Nome", editor)
    assert get_system(system.id).slug == "erp-admin"


def test_rename_sem_permissao(owner_system):
    _, system = owner_system
    other = auth.create_user("other@sys.local", "pw", UserType.editor.value)
    with pytest.raises(NotPermitted):
        rename_system(system, "Nope", other)


def test_set_provider_audita(owner_system):
    editor, system = owner_system
    set_provider(system.id, "anthropic", "claude-3-5-sonnet-latest", actor=editor)
    fresh = get_system(system.id)
    assert fresh.provider == "anthropic" and fresh.model == "claude-3-5-sonnet-latest"
    entries = [e for e in audit.list_by_system(system.id) if e["action"] == "system.provider"]
    assert entries and entries[0]["details"]["provider"] == "anthropic"


def test_set_provider_exige_modelo(owner_system):
    _, system = owner_system
    with pytest.raises(ValueError):
        set_provider(system.id, "glm", "")
    with pytest.raises(ValueError):
        set_provider(system.id, "", "glm-4.6")


def test_mapa_de_modelos_por_provedor():
    assert set(KNOWN_MODELS) >= {"glm", "anthropic", "openai"}
    assert models_for("glm")[0] == "glm-4.6"
    assert models_for("anthropic", "claude-3-5-haiku-latest")[0] == "claude-3-5-haiku-latest"
    assert models_for("desconhecido", "x-model") == ["x-model"]