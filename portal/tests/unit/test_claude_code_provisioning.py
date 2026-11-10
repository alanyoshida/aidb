"""Unitários da geração de config do perfil claude-code (change
add-claude-code-agent-profile, tasks 5.1/5.3 — achado D6 durante a
implementação: acesso ao banco via o mesmo gated-mcp do opencode)."""

import json

import pytest
from unittest.mock import patch

from appaiforge import auth
from appaiforge.config import get_settings
from appaiforge.models import UserType
from appaiforge.provisioning import db_connections_manifest, write_claude_code_config
from appaiforge.services import catalog, connections
from appaiforge.services.systems import create_system


@pytest.fixture()
def editor(clean_db):
    catalog.ensure_presets()
    return auth.create_user("cc-prov@t.local", "pw", UserType.editor.value)


@pytest.fixture()
def target(live_pg):
    return live_pg


def _settings_json(tmp_path):
    with open(tmp_path / "settings.json") as f:
        return json.load(f)


def test_settings_json_tem_baseurl_do_broker_dialeto_anthropic(editor, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_URL", "http://broker:4001")
    get_settings.cache_clear()
    try:
        system = create_system(editor, "CC", "cc-broker", agent_profile="claude-code")
        write_claude_code_config(system, str(tmp_path), [])
        config = _settings_json(tmp_path)
        # dialeto anthropic: sem "/v1" (ver _broker_base) - mesma regra que o
        # perfil opencode já usa pro provider "anthropic"
        assert config["env"]["ANTHROPIC_BASE_URL"] == "http://broker:4001"
    finally:
        get_settings.cache_clear()


def test_settings_json_sem_baseurl_quando_broker_desligado(editor, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "false")
    get_settings.cache_clear()
    try:
        system = create_system(editor, "CC2", "cc-sem-broker", agent_profile="claude-code")
        write_claude_code_config(system, str(tmp_path), [])
        config = _settings_json(tmp_path)
        assert "ANTHROPIC_BASE_URL" not in config["env"]
    finally:
        get_settings.cache_clear()


def test_settings_json_nunca_carrega_credencial(editor, tmp_path):
    """Spec agent-runtime, "Perfil não carrega segredo"."""
    system = create_system(editor, "CC3", "cc-sem-segredo", agent_profile="claude-code")
    write_claude_code_config(system, str(tmp_path), [])
    raw = (tmp_path / "settings.json").read_text()
    assert "ANTHROPIC_API_KEY" not in raw
    assert "sk-ant" not in raw


def test_sem_conexao_nao_grava_mcp_servers_json(editor, tmp_path):
    system = create_system(editor, "CC4", "cc-sem-conexao", agent_profile="claude-code")
    write_claude_code_config(system, str(tmp_path), [])
    assert not (tmp_path / "mcp-servers.json").exists()


def test_com_conexao_grava_mcp_servers_json_com_dsn_de_loopback(editor, tmp_path, target):
    """Mesmo padrão de write_opencode_config: com o manifesto do sidecar, o
    comando do MCP aponta pro loopback (porta agent_port) sem credencial."""
    system = create_system(editor, "CC5", "cc-com-conexao", agent_profile="claude-code")
    with patch("appaiforge.services.connections._refresh_provisioning"):
        connections.register_connection(
            system, "vendas", target["host"], target["port"], target["database"],
            target["username"], target["password"],
        )
    manifest = db_connections_manifest(system.id)
    write_claude_code_config(system, str(tmp_path), manifest)

    with open(tmp_path / "mcp-servers.json") as f:
        config = json.load(f)
    servers = config["mcpServers"]
    assert list(servers.keys()) == ["vendas"]
    entry = servers["vendas"]
    assert entry["args"][0] == "/opt/gated-mcp/mcp_server.py"
    url = entry["args"][1]
    assert url.startswith("postgresql://127.0.0.1:")
    assert "@" not in url
    assert entry["args"][2] == "postgres"
    assert entry["args"][3] == "read_write"


def test_config_format_claude_code_settings_registrado_no_dispatch(editor, tmp_path):
    from appaiforge.provisioning import _config_writers

    assert _config_writers()["claude-code-settings"] is write_claude_code_config
