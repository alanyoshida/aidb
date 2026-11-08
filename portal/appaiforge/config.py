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
    # Etapa 2 do confinamento (capability agent-sandbox): exige Landlock no
    # host para criar sistemas novos (sandboxed), em vez de degradar
    # silenciosamente para reduced. Hosts de dev/CI sem Landlock desligam
    # (APPAIFORGE_REQUIRE_SANDBOX=false) e aceitam a degradação visível.
    require_sandbox: bool = True

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

    # Broker de inferência (etapa 3, ADR 0020). Desligado por padrão: o
    # provisionamento continua injetando a chave real até o rollout.
    inference_broker_enabled: bool = False
    inference_broker_port: int = 4001
    # Base do LiteLLM vista pelo broker na rede interna (sem porta publicada).
    litellm_base_url: str = "http://litellm:4000"
    # Chave do LiteLLM usada/injetada pelo broker (nunca vai ao container).
    litellm_api_key: str = ""
    # Allowlist de hosts de destino do broker (separados por vírgula).
    inference_broker_allowed_hosts: str = "litellm,localhost,127.0.0.1"
    # Portal visto pelo broker para resolver run/sessão e registrar uso.
    portal_internal_url: str = "http://portal:8080"
    # Broker visto pelo portal para cancelar requisições em andamento.
    inference_broker_url: str = "http://broker:4001"
    # Segredo compartilhado entre portal e broker nas chamadas internas.
    inference_broker_service_token: str = ""

    # Gate de banco no data plane (etapa 4 do confinamento, change
    # db-proxy-gate-data-plane). Segredo compartilhado entre o portal e o
    # sidecar do proxy (mesmo padrão do broker).
    db_gate_proxy_service_token: str = ""
    # "enforce" (default desde a task 7.3, por pedido do operador): o proxy
    # aplica a decisão de verdade — bloqueada e confirmável são recusadas na
    # hora, sem pedir aprovação a ninguém (achado ao vivo: segurar e pedir
    # aprovação deixava passar disfarces de SQL destrutivo se alguém
    # aprovasse por hábito). "shadow" (task 6.1): classifica e audita sem
    # segurar nada, pra comparar com os globs de permission.bash antes de
    # confiar no proxy (spike S5, task 6.2) — ainda disponível por flag pra
    # quem quiser esse período de observação.
    db_gate_mode: str = "enforce"

    session_ttl_days: int = 7
    identity_token_ttl_seconds: int = 60

    # Os horários são gravados em UTC; a UI os converte para este fuso.
    display_timezone: str = "America/Sao_Paulo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
