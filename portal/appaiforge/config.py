"""Configuração central do portal (env-driven)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Modelos conhecidos por provedor de LLM; o primeiro é o padrão (usado no select da UI).
KNOWN_MODELS: dict[str, list[str]] = {
    "glm": ["glm-4.6"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
}

PROVIDERS: list[str] = list(KNOWN_MODELS)


def models_for(provider: str, current: str | None = None) -> list[str]:
    """Modelos conhecidos do provedor; o modelo atual aparece primeiro quando conhecido."""
    models = list(KNOWN_MODELS.get(provider, []))
    if not models:
        return [current] if current else []
    if current and current in models:
        models.remove(current)
        models.insert(0, current)
    return models


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APPAIFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://appaiforge:appaiforge@localhost:5432/appaiforge"
    # Chave mestra: deriva a chave Fernet e diferencia ambientes. Obrigatória em produção.
    secret_key: str = "dev-only-change-me"

    # Docker
    base_image: str = "appaiforge/base:0.1.0"
    docker_network: str = "appaiforge-net"
    # Raiz dos workspaces visível ao portal (dentro do container do portal em compose).
    workspaces_dir: str = "/workspaces"
    # Mesma raiz vista pelo host — usada para bind-mount nos containers de sistema.
    host_workspaces_dir: str = "/var/lib/appaiforge/workspaces"
    # Raiz dos configs de agente visível ao portal (fora do workspace, fora do alcance do agente).
    configs_dir: str = "/configs"
    # Mesma raiz vista pelo host — usada para bind-mount (read-only) nos containers de sistema.
    host_config_dir: str = "/var/lib/appaiforge/configs"

    # Traefik file provider: diretório compartilhado com o Traefik onde o portal
    # escreve a configuração dinâmica das rotas /apps/{slug}.
    dynamic_config_dir: str = "/dynamic"

    # Limites padrão por container de sistema (ADR 0013).
    container_cpus: float = 2.0
    container_mem_mb: int = 2048
    container_disk_gb: int = 10
    # Teto de processos (pids_limit), ADR 0018. Valor provisório, generoso o
    # bastante para uv/npm abrirem muitos processos curtos durante a geração;
    # calibrar com margem a partir de uma execução real (roadmap, etapa 2).
    container_pids_limit: int = 512
    max_systems: int = 10

    # Infra do container de sistema
    harness_port: int = 4096
    app_port: int = 8080

    # Defaults de provedor LLM (ADR 0012)
    default_provider: str = "glm"
    default_model: str = "glm-4.6"
    # BaseURL do GLM no opencode: coding plan da Z.ai tem quota própria (2026-11-02)
    glm_base_url: str = "https://api.z.ai/api/coding/paas/v4"

    # "opencode" (real, via rede Docker) ou "fake" (E2E determinístico, ADR 0016)
    harness_mode: str = "opencode"
    opencode_port: int = 4096

    session_ttl_days: int = 7
    identity_token_ttl_seconds: int = 60

    # Os horários são gravados em UTC; a UI os converte para este fuso.
    display_timezone: str = "America/Sao_Paulo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
