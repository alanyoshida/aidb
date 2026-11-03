"""Unitários da geração do opencode.json por tipo de provedor (tasks 3.1, 3.2)."""

import json

import pytest

from appaiforge import auth
from appaiforge.models import ProviderKey, UserType
from appaiforge.provisioning import _provider_env, write_opencode_config
from appaiforge.security import encrypt_secret
from appaiforge.services import catalog
from appaiforge.services.systems import create_system

GLM_BASE = "https://api.z.ai/api/coding/paas/v4"


@pytest.fixture()
def editor(clean_db):
    catalog.ensure_presets()
    return auth.create_user("prov@t.local", "pw", UserType.editor.value)


def _config(tmp_path, system):
    write_opencode_config(system, str(tmp_path))
    with open(tmp_path / "opencode.json") as f:
        return json.load(f)


def test_glm_preset_mantem_comportamento(editor, tmp_path):
    system = create_system(editor, "G", "prov-glm")
    config = _config(tmp_path, system)
    assert config["model"] == "zhipuai/glm-4.6"
    assert config["provider"] == {"zhipuai": {"options": {"baseURL": GLM_BASE}}}


def test_openrouter_preset_sem_bloco_de_provider(editor, tmp_path):
    system = create_system(editor, "OR", "prov-or", provider="openrouter", model="openai/gpt-4o")
    config = _config(tmp_path, system)
    assert config["model"] == "openrouter/openai/gpt-4o"
    assert "provider" not in config


def test_provedor_openai_compatible(editor, tmp_path):
    catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1",
                            models=["m1", "m2"], actor=None)
    system = create_system(editor, "M", "prov-mia", provider="minha-ia", model="m2")
    config = _config(tmp_path, system)
    assert config["model"] == "minha-ia/m2"
    block = config["provider"]["minha-ia"]
    assert block["npm"] == "@ai-sdk/openai-compatible"
    assert block["options"]["baseURL"] == "https://api.minha.ai/v1"
    assert set(block["models"]) == {"m1", "m2"}


def test_provider_env_usa_env_name_do_catalogo(editor):
    catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1", actor=None)
    from appaiforge.db import session_scope

    with session_scope() as s:
        s.add(ProviderKey(provider="minha-ia", key_encrypted=encrypt_secret("segredo")))
    assert _provider_env("minha-ia") == {"MINHA_IA_API_KEY": "segredo"}
    assert _provider_env("glm") == {}  # preset sem chave cadastrada