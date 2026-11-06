"""Unitários do sync de chaves do catálogo com o LiteLLM (task 5.1)."""

from appaiforge.services.litellm_sync import deployments_for


def test_deployments_glm_usa_rota_openai_compatible():
    provider = {
        "id": "glm", "provider_id": "zhipuai", "kind": "native",
        "base_url": None, "models": ["glm-4.6"],
    }
    dep = deployments_for(provider, "chave-glm")[0]
    assert dep["model_name"] == "zhipuai/glm-4.6"
    assert dep["litellm_params"]["model"] == "openai/glm-4.6"
    assert dep["litellm_params"]["api_base"].endswith("/v4")
    assert dep["litellm_params"]["api_key"] == "chave-glm"
    assert dep["model_info"]["id"] == "aidb:zhipuai/glm-4.6"


def test_deployments_openrouter_nativo():
    provider = {
        "id": "openrouter", "provider_id": "openrouter", "kind": "native",
        "base_url": None, "models": ["openai/gpt-4o"],
    }
    dep = deployments_for(provider, "chave-or")[0]
    assert dep["model_name"] == "openrouter/openai/gpt-4o"
    assert dep["litellm_params"] == {"model": "openrouter/openai/gpt-4o", "api_key": "chave-or"}


def test_deployments_openai_compatible_usa_base_url():
    provider = {
        "id": "minha-ia", "provider_id": "minha-ia", "kind": "openai-compatible",
        "base_url": "https://api.minha.ai/v1", "models": ["m2"],
    }
    dep = deployments_for(provider, "chave-custom")[0]
    assert dep["model_name"] == "minha-ia/m2"
    assert dep["litellm_params"]["model"] == "openai/m2"
    assert dep["litellm_params"]["api_base"] == "https://api.minha.ai/v1"


def test_deployments_anthropic_nativo():
    provider = {
        "id": "anthropic", "provider_id": "anthropic", "kind": "native",
        "base_url": None, "models": ["claude-3-5-sonnet-latest"],
    }
    dep = deployments_for(provider, "chave-anthropic")[0]
    assert dep["model_name"] == "anthropic/claude-3-5-sonnet-latest"
    assert dep["litellm_params"]["model"] == "anthropic/claude-3-5-sonnet-latest"
    assert "api_base" not in dep["litellm_params"]
