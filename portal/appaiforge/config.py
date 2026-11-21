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

    # Driver de provisionamento ativo (change `add-kubernetes-driver`, etapa 8 do roadmap de
    # confinamento) — "docker" (padrão, único hoje em produção) ou "kubernetes". Seleciona qual
    # `appaiforge.drivers.ProvisioningDriver` `get_driver()` instancia; nenhum sistema escolhe
    # driver por si (requirement "Driver de provisionamento é escolha de configuração").
    provisioning_driver: str = "docker"
    # Namespace do cluster onde o driver Kubernetes cria Pod/PVC/ConfigMap/Service por sistema.
    k8s_namespace: str = "appaiforge"
    # Contexto do kubeconfig a usar — nunca o "current-context" implícito (achado real: o
    # current-context do kubeconfig deste host mudou entre dois passos manuais desta mesma
    # validação, sem nenhuma ação deste driver; depender dele é frágil). Vazio = comportamento
    # do cliente padrão (current-context), só aceitável fora deste cluster de validação.
    k8s_kubeconfig_context: str = "kind-appaiforge-dev"

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
    # Raiz dos repositórios git dos sistemas sob o driver Docker (change
    # `isolate-workspace-repository`): o workspace é só a árvore de trabalho e o repositório
    # (objetos, refs, config, hooks) vive aqui, num volume montado SÓ no portal — nenhum
    # container de sistema o monta, então nada que o agente escreve chega à config do git.
    gitdirs_dir: str = "/gitdirs"
    # Papel desta instalação do portal (change `add-deploy-only-system`, D1): `development`
    # (padrão: sistemas com agente e só implantação) ou `production` (só sistemas só
    # implantação — nenhum agente é criado nem provisionado).
    installation_role: str = "development"
    # Exceção, SÓ PARA TESTES, à exigência de host Docker próprio do portal de produção
    # (change add-production-portal-install, D3): com ela, a subida só registra aviso.
    allow_shared_docker_host: bool = False
    # Implantação de versões em sistemas só implantação (change add-deploy-only-system, D5/D7)
    deploy_health_timeout: float = 90.0
    deploy_health_interval: float = 2.0
    deploy_poll_interval: float = 60.0
    # Endereço do portal visto pelo GitLab, para o webhook; vazio = public_base_url.
    webhook_base_url: str = ""
    # Cópias bare de retransmissão, por sistema, de onde o portal fala com o repositório remoto
    # (change `add-system-git-remote`, design D1). Também só o portal monta. Cache reconstruível.
    git_relays_dir: str = "/git-relays"

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

    # Autenticação (change add-oidc-sso). "local" (e-mail/senha, padrão) ou "oidc" (SSO
    # contra IdP externo). O modo é gravado na base no primeiro boot e não pode mudar
    # depois (requirement "Modo de autenticação fixado na instalação").
    auth_mode: str = "local"
    # URL pública do portal, como o navegador a vê (ex.: http://localhost:8082). Base do
    # redirect_uri e do post_logout_redirect_uri no modo oidc.
    public_base_url: str = ""
    # Emissor público do IdP (valida `iss`; ex.: http://localhost:8180/realms/aidb).
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    # Caminho (com ponto) do claim de papéis no access token e do claim de grupos.
    oidc_roles_claim: str = "realm_access.roles"
    oidc_groups_claim: str = "groups"
    # Base interna do IdP para chamadas servidor-a-servidor (discovery/token/JWKS), quando o
    # portal não alcança o IdP pelo endereço público (ex.: http://keycloak:8080 no compose).
    oidc_internal_base_url: str = ""
    # Intervalo máximo entre revalidações da sessão junto ao IdP (spec: no máximo 5 min).
    oidc_revalidate_seconds: int = 300
    # Tolerância a falha de rede com o IdP antes de encerrar a sessão (fail-closed).
    oidc_network_grace_seconds: int = 60

    # Admin break-glass: definido só por ENV (hash scrypt de `appaiforge hash-password`).
    breakglass_email: str = ""
    breakglass_password_hash: str = ""
    breakglass_session_hours: int = 8
    # Rate limit da rota de login local: N falhas por (IP, e-mail) bloqueiam pela janela.
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900

    # Telemetria OTel (change agent-telemetry-otel / agent-telemetry-backend-agnostic).
    # Vazio = SDK segue no-op (sem exporter configurado); nenhum código do
    # portal/broker decide isto por `if`, só a presença do endpoint liga a
    # exportação. Aponta sempre para um Collector (nunca direto para um
    # backend específico) - a escolha do backend é configuração do Collector.
    otel_traces_endpoint: str = ""
    otel_logs_endpoint: str = ""
    # Retenção dos spans persistidos em `agent_telemetry_spans` pro Debug
    # log (change agent-telemetry-backend-agnostic) - escopo estrito a essa
    # tabela; AgentRun/RunEventRecord continuam sem limpeza automática.
    otel_span_retention_days: int = 30

    # Os horários são gravados em UTC; a UI os converte para este fuso.
    display_timezone: str = "America/Sao_Paulo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
