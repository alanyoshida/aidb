"""Provisionamento de sistemas, agnóstico de driver (ADR 0012/0013; specs container-lifecycle,
db-connections; change `add-kubernetes-driver` para a extração do driver).

Uma unidade de execução por sistema (container Docker ou Pod Kubernetes, a depender do driver
ativo — `appaiforge.drivers.get_driver()`): workspace e config persistentes, env com credenciais,
limites de recursos, política de reinício e reconciliação. Este módulo cuida só da parte
agnóstica (env, config, manifesto de conexões); a criação/remoção/reconciliação da unidade de
execução em si fica no driver. Também gera o opencode.json com provedor/modelo e um MCP server
por conexão (task 5.4).
"""

import json
import logging
import os
import re

import docker
from afsupervisor.sandbox import landlock_abi
from sqlalchemy import func, select, update

from . import telemetry
from .config import get_settings
from .db import session_scope
from .edge import publish_app, system_container_name, unpublish_app
from .models import ChatSession, DbConnection, ExecutionMode, ProviderKey, System, SystemStatus
from .security import decrypt_secret
from .services.connections import connection_string, get_connection_secret

log = logging.getLogger(__name__)
_telemetry_log = telemetry.get_logger()

# Faixa de portas de loopback do sidecar de gate de banco (etapa 4 do
# confinamento, change db-proxy-gate-data-plane) — cada sistema tem seu
# próprio netns (o sidecar entra nele via `network_mode: container:<id>`),
# então a faixa pode se repetir entre sistemas sem colidir. Fora de 5432/3306
# (portas "reais" dos bancos) para nunca ser confundida com elas em debug.
DB_GATE_PORT_BASE = 15400

# Porta de loopback do proxy HTTP(S) de saída (change agent-https-forward-proxy)
# — uma só por sistema (ao contrário do proxy de banco, não há "uma por
# conexão"), fora da faixa do DB_GATE_PORT_BASE pra nunca colidir mesmo com
# muitas conexões cadastradas num sistema.
HTTPS_PROXY_PORT = 15500


class CapacityReached(Exception):
    pass


class SandboxUnavailable(Exception):
    """Host sem suporte a Landlock e `require_sandbox` ligado (produção)."""

    pass


def decide_execution_mode() -> tuple[ExecutionMode, str]:
    """Modo de execução de um sistema novo, pela sonda de Landlock do host
    (capability agent-sandbox, etapa 2 do confinamento).

    Chamado por `services.systems.create_system` no momento em que a linha
    é criada — nunca em `provision_system`, que só consome o modo já
    persistido. Devolve (modo, aviso); aviso é "" quando não há degradação
    a comunicar. Levanta `SandboxUnavailable` quando o host não suporta
    Landlock e `settings.require_sandbox` é `True`: a chamadora não deve
    criar a linha do sistema nesse caso, para não prometer um confinamento
    que o host não tem como entregar."""
    if landlock_abi() > 0:
        return ExecutionMode.sandboxed, ""
    settings = get_settings()
    if settings.require_sandbox:
        raise SandboxUnavailable(
            "host sem suporte a Landlock; defina APPAIFORGE_REQUIRE_SANDBOX=false "
            "para permitir sistemas em modo reduced neste host"
        )
    return (
        ExecutionMode.reduced,
        "sistema criado em modo reduced: host sem suporte a Landlock (confinamento desligado)",
    )


def _docker() -> docker.DockerClient:
    return docker.from_env()


def ensure_network() -> None:
    """Delega ao driver ativo (change `add-kubernetes-driver`, task 1.2) — pro driver Docker,
    garante a rede bridge compartilhada; outro driver garante o que precisar (ex.: namespace)."""
    from .drivers import get_driver

    get_driver().ensure_ready()


def _provider_env(provider: str) -> dict[str, str]:
    """Env da chave do provedor, com o nome que o opencode espera (ADR 0004)."""
    from .services import catalog

    provider_def = catalog.get_provider(provider)
    env_name = provider_def["env_name"] if provider_def else f"{provider.upper()}_API_KEY"
    env: dict[str, str] = {}
    with session_scope() as s:
        key = s.get(ProviderKey, provider)
        if key is not None:
            env[env_name] = decrypt_secret(key.key_encrypted)
    return env


def _broker_base(provider_id: str) -> str:
    """BaseURL do broker vista pelo container do agente, por dialeto."""
    base = get_settings().inference_broker_url.rstrip("/")
    # Anthropic usa /v1/messages a partir da raiz; os demais usam o prefixo /v1.
    return base if provider_id == "anthropic" else f"{base}/v1"


def _broker_credential_env(system: System) -> dict[str, str]:
    """Token opaco na env de credencial do perfil, no lugar da chave real."""
    from . import inference_token
    from .agent_profiles import get_profile, resolve_credential_env

    env_name = resolve_credential_env(get_profile(system.agent_profile), system.provider)
    return {env_name: inference_token.token_for_system(system)}


def _broker_connect_port() -> int:
    """Porta do broker de inferência, pro Landlock de rede do agente (etapa
    5, change agent-network-perimeter) — a regra do Landlock é só por porta,
    agnóstica de endereço (design.md), então nem precisa resolver o host do
    broker, só a porta que `inference_broker_url` declara."""
    from urllib.parse import urlparse

    parsed = urlparse(get_settings().inference_broker_url)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _broker_destination() -> tuple[str, int]:
    """Host:porta do broker de inferência, para a allow-list do proxy
    HTTP(S) de saída (change `agent-https-forward-proxy`, D2) — diferente
    de `_broker_connect_port` (só a porta, pro Landlock que é agnóstico de
    endereço), aqui o host importa: a allow-list deste proxy é por
    `host:porta`, não só porta."""
    from urllib.parse import urlparse

    parsed = urlparse(get_settings().inference_broker_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname or "broker", port


# Registros de pacote tocados por `pip`/`npm`/`uv` numa instalação comum —
# confirmado por spike real (design.md, task 1.2): nenhum CDN/mirror extra
# apareceu para `requests`/`left-pad`/`httpx`. Não cobre instalação direto
# de git (risco já registrado no design).
PACKAGE_REGISTRY_HOSTS: tuple[tuple[str, int], ...] = (
    ("pypi.org", 443),
    ("files.pythonhosted.org", 443),
    ("registry.npmjs.org", 443),
)


def default_https_allowlist(system: System) -> list[tuple[str, int]]:
    """Allow-list padrão (D2) do proxy HTTP(S) de saída pra um sistema: o
    host do provedor de LLM configurado quando o broker de inferência está
    desligado (global, `inference_broker_enabled`), OU `host:porta` do
    broker quando está ligado — nunca os dois, porque o endpoint que o
    agente usa (etapa 3) só aponta pra um dos dois — mais os registros de
    pacote, iguais para todo sistema."""
    entries: list[tuple[str, int]] = list(PACKAGE_REGISTRY_HOSTS)
    if get_settings().inference_broker_enabled:
        entries.append(_broker_destination())
    else:
        from .services import catalog

        provider = catalog.get_provider(system.provider)
        if provider is not None:
            host = catalog.provider_host(provider)
            if host:
                entries.append((host, 443))
    return entries


_LOOPBACK_SCHEMES = {"postgres": "postgresql", "mysql": "mysql"}


def _loopback_dsn(kind: str, port: int, database: str) -> str:
    """DSN de loopback sem usuário nem senha (task 5.2) — o proxy injeta a
    credencial real do lado de dentro (sidecar), o container do sistema não
    tem nada a vazar."""
    scheme = _LOOPBACK_SCHEMES.get(kind, "postgresql")
    return f"{scheme}://127.0.0.1:{port}/{database}"


def db_connections_manifest(system_id: str) -> list[dict]:
    """Conexões Postgres/MySQL do sistema com a credencial real e as duas
    portas de loopback (agente/app, D4) — vai só no env do sidecar (task
    5.1/5.2), nunca no do sistema. BigQuery fica fora: é HTTPS, não passa
    pelo proxy de wire protocol (Non-Goals do design)."""
    with session_scope() as s:
        conns = s.execute(
            select(DbConnection)
            .where(DbConnection.system_id == system_id, DbConnection.kind.in_(["postgres", "mysql"]))
            .order_by(DbConnection.created_at)
        ).scalars().all()
        conn_ids = [c.id for c in conns]
    manifest = []
    for i, conn_id in enumerate(conn_ids):
        conn, secret = get_connection_secret(conn_id)
        agent_port = DB_GATE_PORT_BASE + i * 2
        manifest.append({
            "name": conn.name,
            "kind": conn.kind,
            "dsn": connection_string(conn, secret),
            "database": conn.database,
            "agent_port": agent_port,
            "app_port": agent_port + 1,
        })
    return manifest


def _connection_env(system_id: str, manifest: list[dict]) -> dict[str, str]:
    """`DATABASE_URL_<NOME>` do container do sistema — loopback (porta
    `app`) sem credencial para Postgres/MySQL; BigQuery segue com a
    credencial real (não tem sidecar, é HTTPS)."""
    from .services.connections import get_connection_secret

    manifest_by_name = {m["name"]: m for m in manifest}
    env: dict[str, str] = {}
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system_id)).scalars().all()
        rows = [(c.id, c.name, c.kind, c.database) for c in conns]
    for conn_id, name, kind, database in rows:
        key = _env_name(name)
        entry = manifest_by_name.get(name)
        if entry is not None:
            env[f"DATABASE_URL_{key}"] = _loopback_dsn(kind, entry["app_port"], database)
        else:  # bigquery (ou kind fora do proxy): sem sidecar, credencial real como antes
            conn, secret = get_connection_secret(conn_id)
            env[f"DATABASE_URL_{key}"] = connection_string(conn, secret)
    return env


def _env_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def _bash_permission_globs() -> dict[str, str]:
    """`permission.bash` do opencode.json (task 7.1, change db-proxy-gate-data-plane).

    Em modo `shadow` (default), os globs de SQL continuam pedindo permissão
    — cinto-e-suspensório enquanto o gate no data plane ainda não foi
    validado em uso real (D5, spike S5). Só em `enforce` eles somem: o
    proxy já é o único gate de SQL, perguntar de novo aqui seria atrito
    duplicado. `reply_gate` (`HarnessPort`) continua existindo nos dois
    modos — ele é o mecanismo genérico de resposta a `permission.asked` do
    opencode, usado por pedidos não-SQL (ex.: acesso a diretório fora do
    workspace), que esta mudança não tem nada a ver."""
    if get_settings().db_gate_mode == "enforce":
        return {"*": "allow"}
    return {
        "*": "allow",
        "*psql*": "ask",
        "*DELETE FROM*": "ask",
        "*UPDATE *SET*": "ask",
        "*DROP TABLE*": "ask",
        "*DROP DATABASE*": "ask",
        "*TRUNCATE*": "ask",
        "*ALTER TABLE*": "ask",
        "*INSERT INTO*": "ask",
    }


def write_opencode_config(system: System, config_dir: str, manifest: list[dict]) -> None:
    """Gera opencode.json do sistema: provedor/modelo + MCP por conexão.

    O MCP server (ferramenta do agente) usa o listener de origem `agente`
    do sidecar — DSN de loopback sem credencial para Postgres/MySQL
    (task 5.2); BigQuery segue com a credencial real (sem sidecar)."""
    from .services import catalog

    provider = catalog.get_provider(system.provider)
    provider_id = provider["provider_id"] if provider else system.provider
    manifest_by_name = {m["name"]: m for m in manifest}
    mcp: dict = {}
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system.id)).scalars().all()
        conn_data = [(c.id, c.name) for c in conns]
    for conn_id, conn_name in conn_data:
        conn, secret = get_connection_secret(conn_id)
        entry = manifest_by_name.get(conn_name)
        url = _loopback_dsn(conn.kind, entry["agent_port"], conn.database) if entry is not None else connection_string(conn, secret)
        tool_name = conn_name
        if conn.description:
            tool_name = f"{tool_name} [{conn.description}]"
        if conn.access_mode == "read_only":
            tool_name = f"{tool_name} (somente-leitura)"
        # MCP de LEITURA própria (D2 refinado): escritas do agente passam pelo bash,
        # que é permissionado (spike 2.1 — permissões do opencode não cobrem ferramentas MCP)
        mcp[tool_name] = {
            "type": "local",
            "command": ["python", "/opt/gated-mcp/mcp_server.py", url, conn.kind, conn.access_mode],
            "enabled": True,
        }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider_id}/{system.model}",
        "mcp": mcp,
        # "allow" por pedido do operador: na prática o agente dispara isto sobretudo
        # com caminho absoluto que já está dentro do próprio workspace (falso-positivo
        # frequente), e o atrito de aprovar toda hora pesou mais que a barreira em si
        # — o filesystem fora do workspace ainda não tem confinamento real (Landlock
        # cobre só rede, etapa 5 do roadmap), então isto não piora o que já não
        # estava garantido por outra camada.
        "permission": {"bash": _bash_permission_globs(), "external_directory": "allow"},
    }
    if provider is not None and provider["kind"] == "openai-compatible":
        models = {m: {} for m in (provider["models"] or [])}
        models.setdefault(system.model, {})
        base_url = _broker_base(provider_id) if get_settings().inference_broker_enabled else provider["base_url"]
        config["provider"] = {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider["label"],
                "options": {"baseURL": base_url},
                "models": models,
            }
        }
    else:
        if get_settings().inference_broker_enabled:
            base_url = _broker_base(provider_id)
        else:
            base_url = provider["base_url"] if provider else None
            if not base_url and provider_id == "zhipuai":
                base_url = get_settings().glm_base_url
        if base_url:
            config["provider"] = {provider_id: {"options": {"baseURL": base_url}}}
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "opencode.json"), "w") as f:
        json.dump(config, f, indent=2)


def write_claude_code_config(system: System, config_dir: str, manifest: list[dict]) -> None:
    """Gera settings.json (D3) e, quando o sistema tem alguma DbConnection,
    mcp-servers.json (D6) do sistema claude-code.

    settings.json: só `{"env": {"ANTHROPIC_BASE_URL": ...}}` — a credencial
    vai pela env do container (ANTHROPIC_API_KEY), nunca neste arquivo
    (spec agent-runtime, "Perfil não carrega segredo"). A CLI `claude` só
    fala o dialeto anthropic (sem modo OpenAI-compatible, ao contrário do
    opencode) — a baseURL é sempre a do broker nesse dialeto, independente
    de `system.provider`; sem broker, omite a chave e a CLI usa o endpoint
    padrão dela (api.anthropic.com).

    mcp-servers.json: achado da implementação (design.md D6) — sem isto o
    claude-code não teria nenhum jeito de ler o banco do sistema. Mesmo
    `gated-mcp` que `write_opencode_config` já usa (agnóstico de agente),
    uma entrada por conexão. Sistemas sem conexão nenhuma não ganham o
    arquivo — o shim só passa `--mcp-config` quando ele existe (task 2.4),
    pra não ligar `--strict-mcp-config` à toa num sistema sem ferramenta
    MCP nenhuma pra oferecer."""
    os.makedirs(config_dir, exist_ok=True)

    settings_payload: dict = {"env": {}}
    if get_settings().inference_broker_enabled:
        settings_payload["env"]["ANTHROPIC_BASE_URL"] = _broker_base("anthropic")
    with open(os.path.join(config_dir, "settings.json"), "w") as f:
        json.dump(settings_payload, f, indent=2)

    manifest_by_name = {m["name"]: m for m in manifest}
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system.id)).scalars().all()
        conn_data = [(c.id, c.name) for c in conns]
    if not conn_data:
        return

    mcp_servers: dict = {}
    for conn_id, conn_name in conn_data:
        conn, secret = get_connection_secret(conn_id)
        entry = manifest_by_name.get(conn_name)
        url = _loopback_dsn(conn.kind, entry["agent_port"], conn.database) if entry is not None else connection_string(conn, secret)
        mcp_servers[conn_name] = {
            "command": "python",
            "args": ["/opt/gated-mcp/mcp_server.py", url, conn.kind, conn.access_mode],
        }
    with open(os.path.join(config_dir, "mcp-servers.json"), "w") as f:
        json.dump({"mcpServers": mcp_servers}, f, indent=2)


def _config_writers() -> dict:
    """Despacho do writer de config do agente por `profile["config_format"]`
    (change generalize-agent-runtime-plumbing) — um `config_format` sem
    entrada aqui é falha explícita no provisionamento, nunca um fallback
    silencioso pra outro writer.

    Resolvida a cada chamada (não num dict de módulo): testes substituem
    `provisioning.write_opencode_config`/`write_claude_code_config` via
    monkeypatch, e um dict de módulo guardaria a função original capturada
    na importação, imune a esse monkeypatch."""
    return {
        "opencode-json": write_opencode_config,
        "claude-code-settings": write_claude_code_config,
    }


def write_agent_profile(system: System, config_dir: str, manifest: list[dict]) -> dict:
    """Serializa o perfil de runtime do agente (capability agent-runtime) como
    JSON em config_dir, ao lado do config do agente. Contém só o NOME da env
    de credencial, nunca o valor de nenhum segredo.

    `connect_tcp_ports` combina a porta estática do perfil (53, DNS) com as
    calculadas para este sistema — o `agent_port` (nunca `app_port`: esse é
    da app gerada, que não roda confinada) de cada conexão do manifesto do
    proxy de gate de banco (etapa 4), a porta do broker de inferência quando
    habilitado (etapa 3), e a porta do proxy HTTP(S) de saída (change
    agent-https-forward-proxy) — único jeito de alcançar 443/80, que saíram
    da lista estática do perfil. `bind_tcp_ports` é só a porta do próprio
    harness — o agente confinado nunca precisa escutar em outra (etapa 5,
    change agent-network-perimeter)."""
    from .agent_profiles import get_profile, resolve_credential_env

    profile = get_profile(system.agent_profile)
    connect_tcp_ports = (
        list(profile.get("connect_tcp_ports", []))
        + [m["agent_port"] for m in manifest]
        + [HTTPS_PROXY_PORT]
    )
    if get_settings().inference_broker_enabled:
        connect_tcp_ports.append(_broker_connect_port())
    payload = {
        "agent": profile["agent"],
        "command": profile["command"],
        "cwd": profile["cwd"],
        "config_path": profile["config_path"],
        "config_format": profile["config_format"],
        "credential_env": resolve_credential_env(profile, system.provider),
        "harness_port": profile["harness_port"],
        "readable_paths": profile["readable_paths"],
        "writable_paths": profile["writable_paths"],
        "writable_files": profile.get("writable_files", []),
        "connect_tcp_ports": connect_tcp_ports,
        "bind_tcp_ports": [profile["harness_port"]],
    }
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "agent-profile.json"), "w") as f:
        json.dump(payload, f, indent=2)
    return payload


def refresh_connections(system: System) -> None:
    """Reaplica as conexões vigentes: recria o container (env + opencode.json
    são fixados na criação; o workspace persiste no volume)."""
    provision_system(system)
    publish_app(system)


def provision_system(system: System) -> str:
    """Cria a unidade de execução do sistema (container ou Pod, a depender do driver ativo —
    change `add-kubernetes-driver`); devolve o identificador opaco a persistir.

    Config e manifesto de conexões são agnósticos de driver: o portal escreve os arquivos no seu
    próprio diretório de config (settings.configs_dir/<slug>); como esse diretório chega até a
    unidade de execução (bind mount, PVC etc.) é responsabilidade do driver.
    """
    from .agent_profiles import UnknownProfile, get_profile
    from .drivers import get_driver

    settings = get_settings()
    profile = get_profile(system.agent_profile)
    _check_capacity(system.id)
    ensure_network()
    driver = get_driver()

    # invalida sessões opencode abertas antes de recriar o container
    with session_scope() as s:
        s.execute(
            update(ChatSession)
            .where(ChatSession.system_id == system.id)
            .values(context_reset=True, harness_session_id=None)
        )

    portal_config_dir = os.path.join(settings.configs_dir, system.slug)
    manifest = db_connections_manifest(system.id)
    try:
        config_writer = _config_writers()[profile["config_format"]]
    except KeyError:
        raise UnknownProfile(f"config_format '{profile['config_format']}' sem writer registrado")
    config_writer(system, portal_config_dir, manifest)
    write_agent_profile(system, portal_config_dir, manifest)

    env = {
        "APP_IDENTITY_SECRET": system.identity_secret,
        "APPAIFORGE_SLUG": system.slug,
        "APP_PORT": str(settings.app_port),
        "APP_ROOT_PATH": f"/apps/{system.slug}",
        # Único ponto de entrada fixo do supervisor (ADR 0018, D2): todo o resto
        # do runtime do agente (comando, cwd, porta, credencial) vem de dentro
        # do arquivo que esta env aponta, não de constante nenhuma no supervisor.
        # O diretório em si vem do perfil (profile["config_mount_path"]), não
        # de um literal fixo (change generalize-agent-runtime-plumbing).
        "AIDB_AGENT_PROFILE": f"{profile['config_mount_path']}/agent-profile.json",
        # Diz ao supervisor se ele deve instalar seccomp/Landlock antes do
        # exec do agente (capability agent-sandbox, etapa 2). O modo já está
        # fixado desde a criação do sistema; o supervisor só confia nele.
        "AIDB_EXECUTION_MODE": system.execution_mode.value,
        # Convenção universal que pip/npm/uv/o cliente HTTP do agente já
        # respeitam (change agent-https-forward-proxy, D4) — 443/80 saíram
        # do Landlock estático (agent_profiles.py), então ferramenta que
        # ignora isto falha ao tentar conectar direto, fail-closed aceito.
        "HTTP_PROXY": f"http://127.0.0.1:{HTTPS_PROXY_PORT}",
        "HTTPS_PROXY": f"http://127.0.0.1:{HTTPS_PROXY_PORT}",
        "NO_PROXY": "",
        **(
            _broker_credential_env(system)
            if settings.inference_broker_enabled
            else _provider_env(system.provider)
        ),
        **_connection_env(system.id, manifest),
    }

    container_id = driver.provision(system, env=env, manifest=manifest)
    set_container(system.id, container_id)
    return container_id


def dbgate_sidecar_name(slug: str) -> str:
    return f"{system_container_name(slug)}-dbgate"


def httpsproxy_sidecar_name(slug: str) -> str:
    return f"{system_container_name(slug)}-httpsproxy"


def refresh_https_allowlist(system: System) -> None:
    """Recria só o sidecar do proxy HTTP(S) de saída com a allow-list
    recalculada (change `agent-https-forward-proxy`, controles da seção 4)
    — bem mais leve que `refresh_connections` (que recria o container do
    sistema inteiro, interrompendo sessões): internet habilitada, modo
    restrito e a lista de domínios não mudam nenhuma env do container do
    agente, só a allow-list que o sidecar aplica.

    Delega ao driver ativo (change `add-kubernetes-driver`, task 1.2)."""
    if not system.container_id:
        return
    from .drivers import get_driver

    get_driver().refresh_https_allowlist(system)


def _check_capacity(system_id: str) -> None:
    settings = get_settings()
    with session_scope() as s:
        active = s.execute(
            select(func.count(System.id)).where(
                System.status.in_([SystemStatus.active, SystemStatus.provisioning]),
                System.id != system_id,
            )
        ).scalar_one()
    if active >= settings.max_systems:
        raise CapacityReached(f"teto de {settings.max_systems} sistemas simultâneos atingido")


def set_status_message(system_id: str, message: str) -> None:
    from .services.systems import set_status

    set_status(system_id, SystemStatus.active, message)


def set_container(system_id: str, container_id: str) -> None:
    from .services.systems import set_container as _set

    _set(system_id, container_id)


def healthcheck_url(system: System) -> str:
    """Delega ao driver ativo (change `add-kubernetes-driver`, task 1.2) — a URL interna pra
    alcançar a app varia por driver (DNS do bridge Docker vs. Service DNS do cluster)."""
    from .drivers import get_driver

    return get_driver().healthcheck_url(system)


def stop_and_remove(system: System) -> None:
    """Delega ao driver ativo (change `add-kubernetes-driver`, task 1.2)."""
    from .drivers import get_driver

    get_driver().remove(system)


def start_provisioning_thread(system_id: str) -> None:
    """Provisiona fora do request: thread daemon que atualiza o estado do sistema."""
    import threading

    def work() -> None:
        from .services.systems import get_system, set_status

        system = get_system(system_id)
        if system is None:
            return
        try:
            provision_system(system)
            set_status(system_id, SystemStatus.active, "")
            publish_app(system)
        except Exception as exc:
            log.exception("provisionamento falhou para %s", system.slug)
            set_status(system_id, SystemStatus.error, f"provisionamento falhou: {exc}")

    threading.Thread(target=work, daemon=True, name=f"provision-{system_id}").start()


def reconcile() -> None:
    """Concilia estado real das unidades de execução (container ou Pod, a depender do driver
    ativo — change `add-kubernetes-driver`) com o registrado (boot/periódico)."""
    from .drivers import ComputeUnitNotFound, get_driver

    driver = get_driver()
    with session_scope() as s:
        systems = [
            (sys.id, sys.slug, sys.status, sys.container_id)
            for sys in s.execute(select(System)).scalars()
        ]
    for system_id, slug, status, container_id in systems:
        if status in (SystemStatus.archived, SystemStatus.provisioning):
            continue
        try:
            driver.reconcile_one(system_id, slug)
            publish_app_by_slug(slug)
        except ComputeUnitNotFound:
            log.warning("reconciliação: unidade de execução ausente para %s; recriando", slug)
            from .services.systems import get_system

            system = get_system(system_id)
            if system is not None:
                try:
                    provision_system(system)  # recria sistema + sidecar juntos (task 5.4)
                    publish_app_by_slug(slug)
                except Exception as exc:  # falha visível no estado do sistema
                    from .services.systems import set_status

                    set_status(system_id, SystemStatus.error, f"reconciliação falhou: {exc}")
        _check_connections_health(system_id)


def _check_connections_health(system_id: str) -> None:
    """Verifica saúde de cada conexão do sistema; erros por conexão são silenciados."""
    from .services.connections import check_connection_health

    with session_scope() as s:
        conn_ids = [
            c.id for c in s.execute(select(DbConnection).where(DbConnection.system_id == system_id)).scalars()
        ]
    for conn_id in conn_ids:
        try:
            check_connection_health(conn_id)
        except Exception:
            log.exception("health check falhou para conexão %s", conn_id)


def publish_app_by_slug(slug: str) -> None:
    from .services.systems import get_system_by_slug

    system = get_system_by_slug(slug)
    if system is not None:
        publish_app(system)


def archive_system(system: System, actor_id: str | None = None, actor_email: str | None = None) -> None:
    """Arquiva: para o container, preserva workspace, remove rota (spec container-lifecycle)."""
    stop_and_remove(system)
    unpublish_app(system.slug)
    from .services.systems import set_status

    set_status(system.id, SystemStatus.archived, "")
    _telemetry_log.info(
        "sistema arquivado",
        extra={"system_id": system.id, "slug": system.slug, "actor_id": actor_id, "actor_email": actor_email},
    )


def delete_system(system: System, actor_id: str | None = None, actor_email: str | None = None) -> None:
    """Exclusão definitiva (somente admin): container + workspace (spec)."""
    _telemetry_log.info(
        "sistema excluído definitivamente",
        extra={"system_id": system.id, "slug": system.slug, "actor_id": actor_id, "actor_email": actor_email},
    )
    stop_and_remove(system)
    unpublish_app(system.slug)
    if get_settings().provisioning_driver == "kubernetes":
        # workspace real é a PVC, não `workspaces_dir` local (change
        # `fix-k8s-workspace-materialize-delete`) — só aqui, nunca em `stop_and_remove`/
        # `driver.remove()`, que preserva a PVC para arquivamento/reprovisionamento.
        from .drivers.kubernetes_driver import delete_workspace_pvc

        delete_workspace_pvc(system.slug)
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    if os.path.isdir(workspace):
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
