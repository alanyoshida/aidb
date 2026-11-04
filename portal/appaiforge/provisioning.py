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
from sqlalchemy import func, select, update

from .config import get_settings
from .db import session_scope
from .edge import publish_app, system_container_name, unpublish_app
from .models import ChatSession, DbConnection, ProviderKey, System, SystemStatus
from .security import decrypt_secret
from .services.connections import connection_string, get_connection_secret

log = logging.getLogger(__name__)


class CapacityReached(Exception):
    pass


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


def _connection_env(system_id: str) -> dict[str, str]:
    from .services.connections import get_connection_secret

    env: dict[str, str] = {}
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system_id)).scalars().all()
        ids = [c.id for c in conns]
    for conn_id in ids:
        conn, secret = get_connection_secret(conn_id)
        key = _env_name(conn.name)
        env[f"DATABASE_URL_{key}"] = connection_string(conn, secret)
    return env


def _env_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def write_opencode_config(system: System, config_dir: str) -> None:
    """Gera opencode.json do sistema: provedor/modelo + MCP por conexão."""
    from .services import catalog

    provider = catalog.get_provider(system.provider)
    provider_id = provider["provider_id"] if provider else system.provider
    mcp: dict = {}
    with session_scope() as s:
        conns = s.execute(select(DbConnection).where(DbConnection.system_id == system.id)).scalars().all()
        conn_data = [(c.id, c.name) for c in conns]
    for conn_id, conn_name in conn_data:
        conn, secret = get_connection_secret(conn_id)
        url = connection_string(conn, secret)
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
        # Gate de destrutivas: comandos que executam SQL pedem permissão; o portal
        # classifica (sqlgate) e responde — bloqueada é recusada, confirmável aguarda
        # aprovação no chat, normal é liberada sem atrito.
        "permission": {
            "bash": {
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
        },
    }
    if provider is not None and provider["kind"] == "openai-compatible":
        models = {m: {} for m in (provider["models"] or [])}
        models.setdefault(system.model, {})
        config["provider"] = {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider["label"],
                "options": {"baseURL": provider["base_url"]},
                "models": models,
            }
        }
    else:
        base_url = provider["base_url"] if provider else None
        if not base_url and provider_id == "zhipuai":
            base_url = get_settings().glm_base_url
        if base_url:
            config["provider"] = {provider_id: {"options": {"baseURL": base_url}}}
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "opencode.json"), "w") as f:
        json.dump(config, f, indent=2)


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
    # container antigo com mesma identidade é substituído; remoção é retry-ável
    # (corridas entre provisionamento, refresh de conexões e reconciliação)
    for _ in range(5):
        try:
            old = client.containers.get(container_name)
            old.remove(force=True)
            break
        except docker.errors.NotFound:
            break
        except docker.errors.APIError:
            time.sleep(1)

    host_dir = os.path.join(settings.host_workspaces_dir, system.slug)
    portal_dir = os.path.join(settings.workspaces_dir, system.slug)
    os.makedirs(portal_dir, exist_ok=True)

    host_config_slug = os.path.join(settings.host_config_dir, system.slug)
    portal_config_dir = os.path.join(settings.configs_dir, system.slug)
    write_opencode_config(system, portal_config_dir)

    env = {
        "APP_IDENTITY_SECRET": system.identity_secret,
        "APPAIFORGE_SLUG": system.slug,
        "APP_PORT": str(settings.app_port),
        "APP_ROOT_PATH": f"/apps/{system.slug}",
        **_provider_env(system.provider),
        **_connection_env(system.id),
    }

    limits = {
        "nano_cpus": int(settings.container_cpus * 1e9),
        "mem_limit": f"{settings.container_mem_mb}m",
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

    set_container(system.id, container.id)
    return container.id


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
            client.containers.get(system_container_name(slug))
            publish_app_by_slug(slug)
        except docker.errors.NotFound:
            log.warning("reconciliação: container ausente para %s; recriando", slug)
            from .services.systems import get_system

            system = get_system(system_id)
            if system is not None:
                try:
                    provision_system(system)
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
