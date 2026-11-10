"""Integração com Docker real pro perfil claude-code (change
add-claude-code-agent-profile, task 5.2) — mesmo padrão de
test_provisioning.py pro perfil opencode.

Requer a imagem appaiforge/claude-code:0.1.0 presente no daemon local
(task 3.1/3.2, `docker build -f base-image/Dockerfile.claude-code`).
"""

import os

import pytest

pytestmark = pytest.mark.integration


def _client():
    import docker

    return docker.from_env()


@pytest.fixture()
def claude_code_system(docker_env, clean_db, monkeypatch):
    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system
    from tests.integration.conftest import remove_system_containers

    # credencial via broker (_broker_credential_env) — sem isto, sem broker
    # habilitado o env cai em _provider_env(system.provider), que lê a
    # ProviderKey real da tabela (vazia aqui) e não injeta nada.
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    get_settings.cache_clear()

    catalog.ensure_presets()
    editor = auth.create_user("prov-cc@t.local", "pw", UserType.editor.value)
    sys = create_system(
        editor, "Sistema Claude Code", f"prov-cc-{os.urandom(3).hex()}",
        agent_profile="claude-code", provider="anthropic",
    )
    yield sys
    remove_system_containers(sys.slug)
    get_settings.cache_clear()


def test_sistema_claude_code_sobe_com_imagem_mount_e_env_do_perfil(claude_code_system):
    from appaiforge.agent_profiles import get_profile
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    system = claude_code_system
    provision_system(system)

    container = _client().containers.get(system_container_name(system.slug))
    attrs = container.attrs
    profile = get_profile(system.agent_profile)

    # imagem e mount vêm do perfil (spec agent-runtime) - não exige mudança
    # em provision_system fora do dispatch já genérico (generalize-agent-runtime-plumbing)
    assert attrs["Config"]["Image"] == profile["image"] == "appaiforge/claude-code:0.1.0"
    mounts = {m["Destination"]: m for m in attrs["Mounts"]}
    assert profile["config_mount_path"] in mounts
    assert mounts[profile["config_mount_path"]]["RW"] is False

    env = attrs["Config"]["Env"]
    assert f"AIDB_AGENT_PROFILE={profile['config_mount_path']}/agent-profile.json" in env
    # credencial pela env literal do perfil (achado real, task 1.3) - não
    # ANTHROPIC_AUTH_TOKEN
    assert any(e.startswith("ANTHROPIC_API_KEY=") for e in env)
    assert not any(e.startswith("ANTHROPIC_AUTH_TOKEN=") for e in env)


def test_sistema_claude_code_grava_settings_json_no_config_dir(claude_code_system):
    from appaiforge.config import get_settings
    from appaiforge.provisioning import provision_system

    system = claude_code_system
    provision_system(system)

    config_dir = os.path.join(get_settings().configs_dir, system.slug)
    assert os.path.isfile(os.path.join(config_dir, "settings.json"))
