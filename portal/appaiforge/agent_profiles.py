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
        "readable_paths": ["/opencode-config", "/usr", "/lib", "/opt"],
        "writable_paths": ["/workspace"],
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
