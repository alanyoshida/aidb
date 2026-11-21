"""Unitários de renomear sistema, editar provedor e mapa de modelos (tasks 3.1, 3.2)."""

import pytest

from appaiforge import auth
from appaiforge.config import KNOWN_MODELS, models_for
from appaiforge.models import UserType
from appaiforge.services import audit
from appaiforge.services.systems import (
    NotPermitted,
    create_system,
    get_system,
    rename_system,
    revoke_inference_access,
    set_provider,
)


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


def test_revoke_inference_access_incrementa_versao_e_audita(owner_system):
    from appaiforge import inference_token

    editor, system = owner_system
    old_version = system.inference_token_version
    old_token = inference_token.emit(system.id, old_version)

    revoke_inference_access(system.id, actor=editor)

    fresh = get_system(system.id)
    assert fresh.inference_token_version == old_version + 1

    # token antigo deixa de validar contra a nova versão; o novo valida
    assert inference_token.validate(old_token, fresh.inference_token_version) is None
    new_token = inference_token.emit(system.id, fresh.inference_token_version)
    assert inference_token.validate(new_token, fresh.inference_token_version) == system.id

    entries = [e for e in audit.list_by_system(system.id) if e["action"] == "system.revoke_inference"]
    assert entries
    assert entries[0]["details"] == {"inference_version": old_version + 1}
    assert entries[0]["actor_id"] == editor.id


def test_revoke_inference_sem_permissao(owner_system):
    _, system = owner_system
    other = auth.create_user("other-revoke@sys.local", "pw", UserType.editor.value)
    with pytest.raises(NotPermitted):
        revoke_inference_access(system.id, actor=other)
    assert models_for("anthropic", "claude-3-5-haiku-latest")[0] == "claude-3-5-haiku-latest"
    assert models_for("desconhecido", "x-model") == ["x-model"]

def test_modelo_padrao_segue_o_provedor_escolhido(clean_db):
    """Piloto com LLM real: criar com um provedor que não oferece glm-4.6 gravava glm-4.6, e o
    agente não respondia. Sem modelo escolhido, vale o primeiro do catálogo do provedor."""
    from appaiforge.services import catalog

    catalog.ensure_presets()
    editor = auth.create_user("modelo@sys.local", "pw", UserType.editor.value)
    assert create_system(editor, "GLM", "modelo-glm").model == "glm-4.6"
    anthropic = catalog.get_provider("anthropic")["models"][0]
    assert create_system(editor, "Anthropic", "modelo-anthropic", "anthropic").model == anthropic
    assert create_system(editor, "Escolhido", "modelo-escolhido", "anthropic", "outro").model == "outro"


def test_falha_ao_aplicar_provedor_deixa_o_sistema_em_erro(owner_system, monkeypatch):
    """Antes, a falha só ia para o log e a página mostrava o provedor novo como aplicado."""
    import time

    from appaiforge.models import SystemStatus

    editor, system = owner_system

    def boom(_system):
        raise RuntimeError("segredo ilegível")

    monkeypatch.setattr("appaiforge.provisioning.provision_system", boom)
    set_provider(system.id, "anthropic", "claude-3-5-sonnet-latest", actor=editor)
    deadline = time.time() + 10
    while time.time() < deadline and get_system(system.id).status != SystemStatus.error:
        time.sleep(0.1)
    fresh = get_system(system.id)
    assert fresh.status == SystemStatus.error
    assert "não foi possível aplicar o provedor" in fresh.status_message
