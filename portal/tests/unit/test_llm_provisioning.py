"""Unitários da geração do opencode.json por tipo de provedor (tasks 3.1, 3.2)."""

import json
from unittest.mock import patch

import pytest

from appaiforge import auth
from appaiforge.models import ProviderKey, UserType
from appaiforge.provisioning import _provider_env, write_opencode_config
from appaiforge.security import encrypt_secret
from appaiforge.services import catalog, connections
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


@pytest.fixture()
def target(live_pg):
    return live_pg


def test_nome_tool_com_descricao_e_read_only(editor, tmp_path, target):
    system = create_system(editor, "T", "prov-tool-ro")
    with patch("appaiforge.services.connections._refresh_provisioning"):
        connections.register_connection(
            system, "analytics", target["host"], target["port"], target["database"],
            target["username"], target["password"],
            description="Dados analíticos", access_mode="read_only",
        )
    config = _config(tmp_path, system)
    mcp_keys = list(config["mcp"].keys())
    assert mcp_keys == ["analytics [Dados analíticos] (somente-leitura)"]
    cmd = config["mcp"][mcp_keys[0]]["command"]
    assert cmd[-1] == "read_only"


def test_nome_tool_com_descricao_sem_read_only(editor, tmp_path, target):
    system = create_system(editor, "T2", "prov-tool-rw")
    with patch("appaiforge.services.connections._refresh_provisioning"):
        connections.register_connection(
            system, "operacional", target["host"], target["port"], target["database"],
            target["username"], target["password"],
            description="Banco principal", access_mode="read_write",
        )
    config = _config(tmp_path, system)
    mcp_keys = list(config["mcp"].keys())
    assert mcp_keys == ["operacional [Banco principal]"]
    cmd = config["mcp"][mcp_keys[0]]["command"]
    assert cmd[-1] == "read_write"


def test_nome_tool_sem_descricao_sem_read_only(editor, tmp_path, target):
    system = create_system(editor, "T3", "prov-tool-plain")
    with patch("appaiforge.services.connections._refresh_provisioning"):
        connections.register_connection(
            system, "simples", target["host"], target["port"], target["database"],
            target["username"], target["password"],
        )
    config = _config(tmp_path, system)
    mcp_keys = list(config["mcp"].keys())
    assert mcp_keys == ["simples"]
    cmd = config["mcp"]["simples"]["command"]
    assert cmd[-1] == "read_write"


def test_write_opencode_config_grava_em_config_dir_nao_no_workspace(editor, tmp_path):
    import os

    config_dir = tmp_path / "config"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    system = create_system(editor, "ISO", "prov-iso")
    write_opencode_config(system, str(config_dir))

    assert os.path.isfile(config_dir / "opencode.json"), "opencode.json deve estar em config_dir"
    assert not os.path.exists(workspace_dir / "opencode.json"), "opencode.json NÃO deve estar no workspace_dir"