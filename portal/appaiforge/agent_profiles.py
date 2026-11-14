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
        # Imagem de container do agente (change generalize-agent-runtime-plumbing)
        # — valor igual ao `settings.base_image` que o provisionamento usava
        # fixo antes desta mudança; zero mudança de comportamento.
        "image": "appaiforge/base:0.1.0",
        # Caminho, dentro do container, onde o portal monta (read-only, fora
        # do workspace) o diretório de config deste agente — igual ao
        # literal `/opencode-config` que o provisionamento usava fixo antes.
        "config_mount_path": "/opencode-config",
        "config_path": "/opencode-config/opencode.json",
        "config_format": "opencode-json",
        "credential_env": FROM_PROVIDER,
        "harness_port": 4096,
        # Protocolo que o HarnessPort do portal usa para falar com este
        # agente (agent_queue.HARNESS_IMPLEMENTATIONS) — igual ao único
        # protocolo que existia antes desta mudança.
        "harness_protocol": "opencode-http",
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
    "claude-code": {
        "agent": "claude-code",
        # O supervisor sobe o shim (processo de vida longa, D1 do design da
        # change add-claude-code-agent-profile) — a CLI `claude` em si é
        # invocada por prompt, como subprocesso curto, de dentro do shim.
        "command": ["python3", "/opt/claude-code-shim/shim.py"],
        "cwd": "/workspace",
        "image": "appaiforge/claude-code:0.1.0",
        # Diretório montado só-leitura, fora do workspace (spec agent-runtime,
        # "Perfil entregue ao container sem segredo") — guarda settings.json
        # (D3) e, quando o sistema tem alguma DbConnection, mcp-servers.json
        # (D6). "config_path" aponta pro primeiro; o shim resolve o segundo
        # pela mesma convenção de diretório (claude_code_shim.MCP_CONFIG_PATH).
        "config_mount_path": "/claude-code-config",
        "config_path": "/claude-code-config/settings.json",
        "config_format": "claude-code-settings",
        # Achado real (spike, task 1.3): a CLI aceita ANTHROPIC_API_KEY
        # (header x-api-key) e ANTHROPIC_AUTH_TOKEN (Authorization: Bearer)
        # igualmente, sem validar formato de chave em nenhum dos dois — mas
        # o broker já sabe trocar x-api-key pro dialeto anthropic (é o que
        # o perfil opencode usa, catalog.py PRESETS); ANTHROPIC_AUTH_TOKEN
        # introduziria uma segunda convenção de header sem necessidade.
        "credential_env": "ANTHROPIC_API_KEY",
        "harness_port": 8091,
        "harness_protocol": "claude-code-headless",
        # Achado real (strace -f, task 1.4): além de ~/.claude/** (sessões,
        # config, plugins, transcritos) e ~/.claude.json (config global,
        # escrita atômica via .tmp.*), a CLI também usa ~/.config/anthropic/
        # — uma segunda árvore de config que não estava prevista.
        "readable_paths": [
            "/claude-code-config", "/usr", "/lib", "/opt", "/proc", "/dev",
            "/etc/resolv.conf", "/etc/hosts", "/etc/host.conf", "/etc/nsswitch.conf",
            "/etc/netsvc.conf", "/etc/svc.conf", "/etc/localtime",
            "/etc/ld.so.cache", "/etc/ld.so.preload", "/etc/claude-code",
            "/etc/ssl/certs", "/etc/ssl/cert.pem", "/etc/ssl/ca-bundle.pem",
            "/etc/openssl/certs", "/etc/pki",
        ],
        "writable_paths": [
            "/workspace",
            "/home/agent/.claude",
            "/home/agent/.claude.json",
            "/home/agent/.config/anthropic",
            "/home/agent/.config/git",
            "/home/agent/.npm",
            "/home/agent/.local",
            "/home/agent/.bashrc", "/home/agent/.bash_profile", "/home/agent/.bash_login",
            "/home/agent/.profile",
            "/tmp",
        ],
        # `.gitconfig` especificamente precisa existir como ARQUIVO, não diretório, no primeiro
        # boot (achado real, change `add-kubernetes-driver`, task 8.3): só ele é escrito de
        # dentro do próprio container depois do boot (pelo `git config --global` do checkpoint
        # via exec do driver Kubernetes — o checkpoint do driver Docker roda no processo do
        # portal, fora do container, então nunca tocou nisso antes). Os demais nomes
        # (`.claude.json`, `.bashrc` etc.) ficam em `writable_paths` mesmo sendo arquivos: a CLI
        # os substitui por padrão temp-file-e-rename, que precisa de direito de criar/remover
        # ENTRADA no diretório pai — só uma regra do Landlock no PRÓPRIO diretório (não no
        # arquivo) dá isso; tratá-los como `writable_files` quebra esse padrão (achado real,
        # mesma task: `test_claude_code_e2e.py` passava com eles como diretório vazio e passou a
        # falhar na primeira chamada ao modelo quando movidos para `writable_files`).
        "writable_files": [
            "/home/agent/.gitconfig",
        ],
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
