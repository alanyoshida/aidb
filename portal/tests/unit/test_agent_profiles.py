"""Unitários do registro de perfis de runtime de agente (tasks 1.1/1.2)."""

import pytest

from appaiforge.agent_profiles import FROM_PROVIDER, UnknownProfile, get_profile, resolve_credential_env
from appaiforge.services import catalog


def test_perfil_padrao_resolvido_pelo_nome():
    profile = get_profile("opencode")
    assert profile["agent"] == "opencode"
    assert profile["command"][0] == "opencode"
    assert profile["cwd"] == "/opencode-config"
    assert profile["harness_port"] == 4096
    assert "/workspace" in profile["writable_paths"]
    assert "/opencode-config" in profile["readable_paths"]


def test_sem_nome_devolve_perfil_padrao_da_plataforma():
    assert get_profile() == get_profile("opencode")


def test_nome_desconhecido_falha_explicitamente():
    with pytest.raises(UnknownProfile):
        get_profile("agente-inexistente")


def test_perfil_declara_credential_env_delegado_ao_provedor():
    profile = get_profile("opencode")
    assert profile["credential_env"] == FROM_PROVIDER


@pytest.fixture()
def presets(clean_db):
    catalog.ensure_presets()


def test_resolve_credential_env_glm_para_zhipu(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "glm") == "ZHIPU_API_KEY"


def test_resolve_credential_env_anthropic(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "anthropic") == "ANTHROPIC_API_KEY"


def test_resolve_credential_env_provedor_desconhecido_cai_no_padrao(presets):
    profile = get_profile("opencode")
    assert resolve_credential_env(profile, "foo") == "FOO_API_KEY"


def test_resolve_credential_env_literal_nao_delega(presets):
    """Perfil com credential_env literal (ex.: futuro agente claude-code) não consulta o catálogo."""
    profile = {"credential_env": "ANTHROPIC_API_KEY"}
    assert resolve_credential_env(profile, "qualquer-coisa") == "ANTHROPIC_API_KEY"
