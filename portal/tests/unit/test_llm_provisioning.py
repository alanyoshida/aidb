"""Unitários da geração do opencode.json por tipo de provedor (tasks 3.1, 3.2)."""

import json
from unittest.mock import patch

import pytest

from appaiforge import auth
from appaiforge.models import ProviderKey, UserType
from appaiforge import inference_token
from appaiforge.agent_profiles import get_profile, resolve_credential_env
from appaiforge.config import get_settings
from appaiforge.provisioning import (
    _broker_base,
    _broker_credential_env,
    _provider_env,
    write_opencode_config,
)
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

def test_write_agent_profile_sem_segredo(editor, tmp_path):
    from appaiforge.provisioning import write_agent_profile

    system = create_system(editor, "PERF", "prov-perfil")
    payload = write_agent_profile(system, str(tmp_path))

    with open(tmp_path / "agent-profile.json") as f:
        on_disk = json.load(f)
    assert on_disk == payload
    assert on_disk["credential_env"] == "ZHIPU_API_KEY"  # glm é o padrão; resolvido, não "from_provider"
    serialized = json.dumps(on_disk)
    assert "from_provider" not in serialized
    # nenhum valor de segredo: nem chave de provedor, nem connection string
    assert "api.z.ai" not in serialized
    assert "://" not in serialized


def test_write_agent_profile_declara_comando_cwd_e_porta(editor, tmp_path):
    from appaiforge.provisioning import write_agent_profile

    system = create_system(editor, "PERF2", "prov-perfil-2")
    payload = write_agent_profile(system, str(tmp_path))

    assert payload["command"][0] == "opencode"
    assert payload["cwd"] == "/opencode-config"
    assert payload["harness_port"] == 4096


def test_provision_system_passa_aidb_agent_profile_no_env(editor, tmp_path, monkeypatch):
    """O container recebe AIDB_AGENT_PROFILE apontando para o perfil no mount
    somente-leitura; o supervisor não embute nenhum caminho literal de agente."""
    import docker

    class FakeContainer:
        id = "fake-id"

    captured = {}

    class FakeContainers:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def run(self, **kwargs):
            captured.update(kwargs)
            return FakeContainer()

    class FakeNetworks:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def create(self, name, driver=None):
            pass

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    monkeypatch.setattr("appaiforge.provisioning._docker", lambda: FakeClient())
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "host-workspaces"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "host-configs"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    try:
        from appaiforge.provisioning import provision_system

        system = create_system(editor, "ENV", "prov-env")
        provision_system(system)
    finally:
        get_settings.cache_clear()

    assert captured["environment"]["AIDB_AGENT_PROFILE"] == "/opencode-config/agent-profile.json"
    assert "ANTHROPIC_API_KEY" not in captured["environment"]  # sem chave real injetada à toa


def _provision_with_fake_docker(system, tmp_path, monkeypatch):
    """Monta um provision_system() que não toca o daemon Docker; devolve os
    kwargs que seriam passados a client.containers.run()."""
    import docker

    class FakeContainer:
        id = "fake-id"

    captured = {}

    class FakeContainers:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def run(self, **kwargs):
            captured.update(kwargs)
            return FakeContainer()

    class FakeNetworks:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def create(self, name, driver=None):
            pass

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    monkeypatch.setattr("appaiforge.provisioning._docker", lambda: FakeClient())
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "host-workspaces"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "host-configs"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    try:
        from appaiforge.provisioning import provision_system

        provision_system(system)
    finally:
        get_settings.cache_clear()
    return captured


def test_sistema_reduzido_recebe_identidade_nao_root(editor, tmp_path, monkeypatch):
    system = create_system(editor, "RED", "prov-reduced")
    kwargs = _provision_with_fake_docker(system, tmp_path, monkeypatch)
    assert kwargs["user"] == "1000:1000"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]


def test_sistema_legacy_sobe_como_root_explicito(editor, tmp_path, monkeypatch):
    from appaiforge.models import ExecutionMode
    from appaiforge.db import session_scope
    from appaiforge.models import System as SystemModel

    system = create_system(editor, "OLD", "prov-legacy")
    with session_scope() as s:
        s.get(SystemModel, system.id).execution_mode = ExecutionMode.legacy
    system.execution_mode = ExecutionMode.legacy

    kwargs = _provision_with_fake_docker(system, tmp_path, monkeypatch)
    assert kwargs["user"] == "root"
    assert "cap_drop" not in kwargs
    assert "security_opt" not in kwargs


def test_teto_de_processos_configuravel_chega_ao_container(editor, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_CONTAINER_PIDS_LIMIT", "77")
    system = create_system(editor, "PIDS", "prov-pids")
    kwargs = _provision_with_fake_docker(system, tmp_path, monkeypatch)
    assert kwargs["pids_limit"] == 77


def test_workspace_de_sistema_reduzido_pertence_ao_usuario_do_agente(editor, tmp_path, monkeypatch):
    system = create_system(editor, "CHOWN", "prov-chown")
    _provision_with_fake_docker(system, tmp_path, monkeypatch)
    workspace = tmp_path / "workspaces" / system.slug
    st = workspace.stat()
    assert (st.st_uid, st.st_gid) == (1000, 1000)


def test_broker_ligado_aponta_config_para_o_broker(editor, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_URL", "http://broker:4001")
    get_settings.cache_clear()

    glm = create_system(editor, "BG", "prov-broker-glm")
    assert _config(tmp_path, glm)["provider"]["zhipuai"]["options"]["baseURL"] == "http://broker:4001/v1"

    anthropic = create_system(editor, "BA", "prov-broker-anthropic", provider="anthropic", model="claude-3-5-sonnet-latest")
    assert _config(tmp_path, anthropic)["provider"]["anthropic"]["options"]["baseURL"] == "http://broker:4001"

    assert _broker_base("zhipuai") == "http://broker:4001/v1"
    assert _broker_base("anthropic") == "http://broker:4001"


def test_broker_credential_env_injeta_token_e_nao_chave(editor, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    get_settings.cache_clear()
    system = create_system(editor, "BT", "prov-broker-token")
    env_name = resolve_credential_env(get_profile(), system.provider)
    env = _broker_credential_env(system)
    assert set(env) == {env_name}
    assert env[env_name] == inference_token.token_for_system(system)
    assert env[env_name] != "chave-real-do-provedor"
