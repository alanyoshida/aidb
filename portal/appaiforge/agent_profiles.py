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
        # /etc: a task 7 original liberou o /etc inteiro porque a chamada de
        # rede do agente falhava com "getaddrinfo EAI_AGAIN" sem ele, sem
        # saber ao certo qual arquivo exigia isso — e "/etc" inteiro também
        # libera /etc/passwd e /etc/group (mundialmente legíveis por permissão
        # Unix, ao contrário de /etc/shadow). Revisado: `strace -f` real num
        # `opencode serve` + sessão + prompt (fora do Landlock, só pra
        # observar) mostrou exatamente o conjunto abaixo — resolução de nome
        # (NSS/glibc), fuso horário, cache do linker dinâmico (também sob
        # Landlock: ele se aplica a partir do próprio `exec` do processo) e a
        # cadeia de certificados TLS; nenhuma leitura de /etc/passwd ou
        # /etc/group apareceu. Os caminhos ausentes nesta imagem (`/etc/pki/*`,
        # `/etc/openssl/certs`, `/etc/ld.so.preload`) ficam na lista mesmo
        # assim — `readable_paths` ausente é ignorado em silêncio
        # (`sandbox.apply_landlock`), e cobre a mesma sondagem numa imagem
        # base diferente (ex.: RHEL/Alpine) sem precisar de outro strace.
        "readable_paths": [
            "/opencode-config", "/usr", "/lib", "/opt", "/proc", "/dev",
            "/etc/resolv.conf", "/etc/hosts", "/etc/host.conf", "/etc/nsswitch.conf",
            "/etc/gai.conf", "/etc/netsvc.conf", "/etc/svc.conf", "/etc/localtime",
            "/etc/ld.so.cache", "/etc/ld.so.preload", "/etc/opencode",
            "/etc/ssl/certs", "/etc/ssl/cert.pem", "/etc/ssl/ca-bundle.pem",
            "/etc/openssl/certs", "/etc/pki",
        ],
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
        # Porta TCP sempre liberada para conexão de saída, independente do
        # sistema (etapa 5, change agent-network-perimeter) — só 53 (TCP
        # mesmo: DNS por UDP nunca passa pelo Landlock de rede, que só cobre
        # TCP; isto é só o fallback raro de resposta grande). 443 e 80
        # SAÍRAM desta lista estática (change agent-https-forward-proxy,
        # ADR a registrar): toda saída HTTP(S) do agente passa a ser
        # obrigatoriamente pelo proxy de saída, cuja porta é calculada por
        # sistema em `provisioning.write_agent_profile` e somada a esta
        # lista estática — junto das portas do proxy de gate de banco e do
        # broker, que já eram calculadas ali.
        "connect_tcp_ports": [53],
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
