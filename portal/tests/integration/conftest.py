"""Fixtures compartilhadas dos testes de integração (Docker real)."""

import os

import pytest


@pytest.fixture()
def docker_env(tmp_path, monkeypatch):
    """Ambiente de provisionamento isolado: workspaces e config dinâmica em tmp."""
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    # configs_dir/host_config_dir também precisam ser isolados: write_opencode_config
    # e write_agent_profile escrevem ali, e o default (/configs) não é gravável
    # fora do container do portal.
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "configs"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def system(docker_env, clean_db):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("prov@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Sistema Prov", f"prov-{os.urandom(3).hex()}")
