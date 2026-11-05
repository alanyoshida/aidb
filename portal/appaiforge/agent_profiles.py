"""Perfis de runtime de agente (capability agent-runtime).

Cada sistema roda um agente de código identificado por um perfil nomeado,
declarado aqui em Python (mesmo formato dos PRESETS de services/catalog.py).
O perfil é a fonte única consultada pelo provisionamento (para montar o
container e entregar o arquivo de config do agente) e pelo supervisor do
container (para saber o que executar) — nenhum dos dois conhece o opencode
por nome fora deste módulo.

`credential_env` aceita um nome literal de variável de ambiente, ou o
marcador FROM_PROVIDER, que delega ao catálogo de provedores de LLM: o nome
da env de credencial é uma interação agente × provedor (o opencode usa o nome
que o catálogo de cada provedor dita), não propriedade fixa de um só.
"""

FROM_PROVIDER = "from_provider"

PROFILES: dict[str, dict] = {
    "opencode": {
        "agent": "opencode",
        "command": ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"],
        "cwd": "/opencode-config",
        "config_path": "/opencode-config/opencode.json",
        "config_format": "opencode-json",
        "credential_env": FROM_PROVIDER,
        "harness_port": 4096,
        # /proc: achado da verificação real da etapa 2 (task 7) — sem leitura
        # de /proc, o runtime Bun do opencode (provavelmente /proc/self/maps,
        # usado pelo JIT do JSC) aborta com SIGABRT ~12s depois de subir, sob
        # Landlock. Não amplia o que o agente já enxerga: supervisor e agente
        # rodam como o mesmo uid no mesmo container, então /proc de um já era
        # visível ao outro pela permissão Unix normal, com ou sem Landlock.
        # /etc: outro achado da task 7 — sem leitura de /etc (provavelmente
        # /etc/resolv.conf, que o resolvedor DNS do Bun lê direto, fora da
        # NSS da glibc), toda chamada de rede do agente falhava com
        # "getaddrinfo EAI_AGAIN", mesmo com DNS funcionando normalmente para
        # qualquer outro processo do container. Também não amplia o que já
        # era acessível: /etc/shadow e /etc/gshadow são 0640 root:shadow,
        # fora do alcance do usuário `agent` por permissão Unix comum,
        # Landlock nunca concede além do que a permissão do arquivo permite.
        # /dev: terceiro achado da task 7 — sem leitura de /dev (provavelmente
        # /dev/null, usado para redirecionar a saída de um subprocesso de
        # sondagem), `uv sync` falhava com "Could not detect either glibc
        # version nor musl libc version" e nenhuma dependência era instalada.
        "readable_paths": ["/opencode-config", "/usr", "/lib", "/opt", "/proc", "/etc", "/dev"],
        # Além de /workspace, o mapa real de escrita de uma geração completa
        # (etapa 1, docs/roadmap-confinamento-do-agente.md) mostrou o agente
        # escrevendo em caminhos sob o HOME do usuário `agent` e em /tmp —
        # sem eles, o Landlock da etapa 2 negaria escrita que o agente
        # legitimamente precisa.
        "writable_paths": [
            "/workspace",
            "/home/agent/.cache/opencode",
            "/home/agent/.cache/uv",
            "/home/agent/.npm",
            "/home/agent/.config",
            "/home/agent/.local",
            "/tmp",
        ],
    },
}

DEFAULT_PROFILE = "opencode"


class UnknownProfile(Exception):
    pass


def get_profile(name: str | None = None) -> dict:
    """Perfil pelo nome; sem nome, devolve o perfil padrão da plataforma."""
    key = name or DEFAULT_PROFILE
    profile = PROFILES.get(key)
    if profile is None:
        raise UnknownProfile(f"perfil de agente '{key}' não registrado")
    return dict(profile)


def resolve_credential_env(profile: dict, provider: str) -> str:
    """Nome da env de credencial do perfil, resolvendo FROM_PROVIDER no catálogo."""
    value = profile["credential_env"]
    if value != FROM_PROVIDER:
        return value
    from .services import catalog

    provider_def = catalog.get_provider(provider)
    return provider_def["env_name"] if provider_def else f"{provider.upper()}_API_KEY"
