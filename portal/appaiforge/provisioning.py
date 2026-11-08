"""Provisionamento via Docker API (ADR 0012/0013; specs container-lifecycle, db-connections).

Um container por sistema: bind do workspace, rede interna, env com credenciais,
limites de recursos, restart policy e labels para reconciliação. Também gera o
opencode.json com provedor/modelo e um MCP server por conexão (task 5.4).
"""

import json
import logging
import os
import re
import time

import docker
from afsupervisor.sandbox import landlock_abi
from sqlalchemy import func, select, update

from .config import get_settings
from .db import session_scope
from .edge import publish_app, system_container_name, unpublish_app
from .models import ChatSession, DbConnection, ExecutionMode, ProviderKey, System, SystemStatus
from .security import decrypt_secret
from .services.connections import connection_string, get_connection_secret

log = logging.getLogger(__name__)

# uid/gid do usuário não-root da imagem base (ADR 0018) — deve casar com o
# `useradd --uid 1000 --gid agent` de base-image/Dockerfile. Só se aplica a
# sistemas em ExecutionMode.reduced; o modo legacy sobe como root explícito.
AGENT_UID = 1000
AGENT_GID = 1000

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
    client = _docker()
    name = get_settings().docker_network
    try:
        client.networks.get(name)
    except docker.errors.NotFound:
        client.networks.create(name, driver="bridge")


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

    env_name = resolve_credential_env(get_profile(), system.provider)
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

    profile = get_profile()
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
    """Cria o container do sistema; devolve o container id.

    Workspace é bind-mounted do host (host_workspaces_dir/<slug>); o portal
    cria o diretório dentro do seu próprio mount workspaces_dir.
    """
    settings = get_settings()
    _check_capacity(system.id)
    ensure_network()

    # invalida sessões opencode abertas antes de recriar o container
    with session_scope() as s:
        s.execute(
            update(ChatSession)
            .where(ChatSession.system_id == system.id)
            .values(context_reset=True, harness_session_id=None)
        )

    client = _docker()
    container_name = system_container_name(system.slug)
    # os sidecars dependem do netns do sistema (`network_mode: container:<id>`,
    # D1) — remover primeiro evita um sidecar órfão apontando pra um
    # container que já não existe mais (achado ao recriar via reconciliação)
    _remove_container_if_exists(client, dbgate_sidecar_name(system.slug))
    _remove_container_if_exists(client, httpsproxy_sidecar_name(system.slug))
    # container antigo com mesma identidade é substituído
    _remove_container_if_exists(client, container_name)

    host_dir = os.path.join(settings.host_workspaces_dir, system.slug)
    portal_dir = os.path.join(settings.workspaces_dir, system.slug)
    os.makedirs(portal_dir, exist_ok=True)
    if system.execution_mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        # dono do usuário do agente (ADR 0018): sem isto, o workspace criado
        # pelo portal (root) não seria gravável pelo container não-root, que
        # tanto reduced quanto sandboxed usam. Sistemas legacy não passam por
        # aqui — workspace existente intacto.
        os.chown(portal_dir, AGENT_UID, AGENT_GID)

    host_config_slug = os.path.join(settings.host_config_dir, system.slug)
    portal_config_dir = os.path.join(settings.configs_dir, system.slug)
    manifest = db_connections_manifest(system.id)
    write_opencode_config(system, portal_config_dir, manifest)
    write_agent_profile(system, portal_config_dir, manifest)

    env = {
        "APP_IDENTITY_SECRET": system.identity_secret,
        "APPAIFORGE_SLUG": system.slug,
        "APP_PORT": str(settings.app_port),
        "APP_ROOT_PATH": f"/apps/{system.slug}",
        # Único ponto de entrada fixo do supervisor (ADR 0018, D2): todo o resto
        # do runtime do agente (comando, cwd, porta, credencial) vem de dentro
        # do arquivo que esta env aponta, não de constante nenhuma no supervisor.
        "AIDB_AGENT_PROFILE": "/opencode-config/agent-profile.json",
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

    limits = {
        "nano_cpus": int(settings.container_cpus * 1e9),
        "mem_limit": f"{settings.container_mem_mb}m",
        "pids_limit": settings.container_pids_limit,
    }
    storage_opt = {"size": f"{settings.container_disk_gb}g"}

    kwargs = {
        "image": settings.base_image,
        "name": container_name,
        "hostname": container_name,
        "network": settings.docker_network,
        "environment": env,
        "volumes": {
            host_dir: {"bind": "/workspace", "mode": "rw"},
            host_config_slug: {"bind": "/opencode-config", "mode": "ro"},
        },
        "labels": {
            "appaiforge.system_id": system.id,
            "appaiforge.slug": system.slug,
            "appaiforge.managed": "true",
        },
        "restart_policy": {"Name": "unless-stopped"},
        **limits,
        **_execution_identity(system.execution_mode),
    }
    try:
        container = client.containers.run(detach=True, **kwargs, storage_opt=storage_opt)
    except docker.errors.APIError as exc:
        if "storage-opt" in str(exc) or "size" in str(exc):
            # driver de arquivos do host não suporta quota de disco — segue sem ela
            log.warning("limite de disco não suportado pelo storage driver; container sem quota: %s", exc)
            container = client.containers.run(detach=True, **kwargs)
            set_status_message(system.id, "ativo sem quota de disco (driver do host não suporta storage-opt)")
        else:
            raise

    _provision_dbgate_sidecar(system, container.id, manifest)
    _provision_httpsproxy_sidecar(system, container.id)
    set_container(system.id, container.id)
    return container.id


def dbgate_sidecar_name(slug: str) -> str:
    return f"{system_container_name(slug)}-dbgate"


def _remove_container_if_exists(client: docker.DockerClient, name: str) -> None:
    """Remoção retry-ável (corridas entre provisionamento, refresh de
    conexões e reconciliação — mesmo padrão do container do sistema)."""
    for _ in range(5):
        try:
            client.containers.get(name).remove(force=True)
            break
        except docker.errors.NotFound:
            break
        except docker.errors.APIError:
            time.sleep(1)


def _provision_dbgate_sidecar(system: System, system_container_id: str, manifest: list[dict]) -> None:
    """Sidecar de gate de banco (D1): container próprio, `network_mode:
    container:<id>` do sistema — enxerga o mesmo loopback, mas tem ciclo de
    vida independente e é o único a guardar as credenciais reais das
    conexões (task 5.1/5.2). Sem conexão Postgres/MySQL, não sobe nenhum
    (nada a segurar; BigQuery não passa por aqui)."""
    client = _docker()
    name = dbgate_sidecar_name(system.slug)
    _remove_container_if_exists(client, name)
    if not manifest:
        return

    settings = get_settings()
    env = {
        "SYSTEM_ID": system.id,
        "APPAIFORGE_DB_CONNECTIONS": json.dumps(manifest),
        "APPAIFORGE_PORTAL_INTERNAL_URL": settings.portal_internal_url,
        "APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN": settings.db_gate_proxy_service_token,
        "APPAIFORGE_DB_GATE_MODE": settings.db_gate_mode,
    }
    client.containers.run(
        detach=True,
        image=settings.base_image,
        name=name,
        command=["python", "/opt/dbproxy/sidecar.py"],
        network_mode=f"container:{system_container_id}",
        environment=env,
        labels={
            "appaiforge.system_id": system.id,
            "appaiforge.slug": system.slug,
            "appaiforge.managed": "true",
            "appaiforge.role": "dbgate-sidecar",
        },
        restart_policy={"Name": "unless-stopped"},
    )


def httpsproxy_sidecar_name(slug: str) -> str:
    return f"{system_container_name(slug)}-httpsproxy"


def _provision_httpsproxy_sidecar(system: System, system_container_id: str) -> None:
    """Proxy HTTP(S) de saída (change `agent-https-forward-proxy`, D1):
    container próprio, `network_mode: container:<id>` do sistema — mesmo
    padrão do sidecar de gate de banco. Ao contrário dele, sobe sempre
    (toda saída HTTP(S) do agente passa a depender deste proxy, não só
    sistemas com conexão de banco cadastrada)."""
    client = _docker()
    name = httpsproxy_sidecar_name(system.slug)
    _remove_container_if_exists(client, name)

    from .services.network_policy import final_https_allowlist

    settings = get_settings()
    allow = final_https_allowlist(system)
    env = {
        "LISTEN_PORT": str(HTTPS_PROXY_PORT),
        "ALLOWED_HOSTS": json.dumps(allow),
    }
    client.containers.run(
        detach=True,
        image=settings.base_image,
        name=name,
        command=["python", "/opt/httpproxy/sidecar.py"],
        network_mode=f"container:{system_container_id}",
        environment=env,
        labels={
            "appaiforge.system_id": system.id,
            "appaiforge.slug": system.slug,
            "appaiforge.managed": "true",
            "appaiforge.role": "httpsproxy-sidecar",
        },
        restart_policy={"Name": "unless-stopped"},
    )


def refresh_https_allowlist(system: System) -> None:
    """Recria só o sidecar do proxy HTTP(S) de saída com a allow-list
    recalculada (change `agent-https-forward-proxy`, controles da seção 4)
    — bem mais leve que `refresh_connections` (que recria o container do
    sistema inteiro, interrompendo sessões): internet habilitada, modo
    restrito e a lista de domínios não mudam nenhuma env do container do
    agente, só a allow-list que o sidecar aplica."""
    if not system.container_id:
        return
    _provision_httpsproxy_sidecar(system, system.container_id)


def _execution_identity(mode: ExecutionMode) -> dict:
    """kwargs de identidade de execução do container (ADR 0018, spec container-lifecycle).

    reduced e sandboxed: usuário não-root da imagem, sem capabilities, sem
    escalada de privilégio — sandboxed ganha a camada adicional de
    seccomp/Landlock dentro do container, instalada pelo supervisor (etapa 2,
    capability agent-sandbox), mas a identidade no `docker.containers.run()`
    é a mesma. legacy: `user="root"` explícito — a imagem passou a ter
    usuário não-root como padrão (base-image/Dockerfile), então sistemas
    criados antes desta mudança exigem a sobrescrita para continuar
    acessando o workspace existente (dono root) sem migração.
    """
    if mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        return {
            "user": f"{AGENT_UID}:{AGENT_GID}",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
        }
    return {"user": "root"}


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
    return f"http://{system_container_name(system.slug)}:{get_settings().app_port}/"


def stop_and_remove(system: System) -> None:
    client = _docker()
    try:
        client.containers.get(dbgate_sidecar_name(system.slug)).remove(force=True)
    except docker.errors.NotFound:
        pass
    try:
        client.containers.get(httpsproxy_sidecar_name(system.slug)).remove(force=True)
    except docker.errors.NotFound:
        pass
    try:
        client.containers.get(system_container_name(system.slug)).remove(force=True)
    except docker.errors.NotFound:
        pass


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
    """Concilia estado real dos containers com o registrado (boot/periódico)."""
    client = _docker()
    with session_scope() as s:
        systems = [
            (sys.id, sys.slug, sys.status, sys.container_id)
            for sys in s.execute(select(System)).scalars()
        ]
    for system_id, slug, status, container_id in systems:
        if status in (SystemStatus.archived, SystemStatus.provisioning):
            continue
        try:
            system_container = client.containers.get(system_container_name(slug))
            publish_app_by_slug(slug)
            _reconcile_dbgate_sidecar(system_id, slug, system_container.id)
            _reconcile_httpsproxy_sidecar(system_id, slug, system_container.id)
        except docker.errors.NotFound:
            log.warning("reconciliação: container ausente para %s; recriando", slug)
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


def _reconcile_dbgate_sidecar(system_id: str, slug: str, system_container_id: str) -> None:
    """Sistema presente, mas o sidecar sumiu sozinho (removido manualmente,
    OOM-killed sem restart etc.) — recria só ele, sem derrubar sessões do
    agente nem o container do sistema (task 5.4)."""
    manifest = db_connections_manifest(system_id)
    if not manifest:
        return
    client = _docker()
    try:
        client.containers.get(dbgate_sidecar_name(slug))
        return
    except docker.errors.NotFound:
        pass
    log.warning("reconciliação: sidecar de gate de banco ausente para %s; recriando", slug)
    from .services.systems import get_system

    system = get_system(system_id)
    if system is not None:
        _provision_dbgate_sidecar(system, system_container_id, manifest)


def _reconcile_httpsproxy_sidecar(system_id: str, slug: str, system_container_id: str) -> None:
    """Mesmo racional do `_reconcile_dbgate_sidecar`, pro proxy HTTP(S) de
    saída — esse sobe sempre (nunca condicional a manifesto), então não há
    `if not manifest: return` aqui."""
    client = _docker()
    try:
        client.containers.get(httpsproxy_sidecar_name(slug))
        return
    except docker.errors.NotFound:
        pass
    log.warning("reconciliação: sidecar do proxy HTTP(S) ausente para %s; recriando", slug)
    from .services.systems import get_system

    system = get_system(system_id)
    if system is not None:
        _provision_httpsproxy_sidecar(system, system_container_id)


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


def archive_system(system: System) -> None:
    """Arquiva: para o container, preserva workspace, remove rota (spec container-lifecycle)."""
    stop_and_remove(system)
    unpublish_app(system.slug)
    from .services.systems import set_status

    set_status(system.id, SystemStatus.archived, "")


def delete_system(system: System) -> None:
    """Exclusão definitiva (somente admin): container + workspace (spec)."""
    stop_and_remove(system)
    unpublish_app(system.slug)
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    if os.path.isdir(workspace):
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
