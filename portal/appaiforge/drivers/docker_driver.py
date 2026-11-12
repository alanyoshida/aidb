"""Driver de provisionamento Docker — extraído de `provisioning.py` sem alterar nenhum
comportamento (change `add-kubernetes-driver`, task 1.2). Toda a lógica que fala direto com o SDK
do Docker vive aqui; `provisioning.py` mantém só a orquestração agnóstica de driver (env, config,
manifesto de conexões, nomes de sidecar) e delega a criação/remoção/reconciliação da unidade de
execução a esta classe via `get_driver()`.

Chamadas de volta a `provisioning.py` passam pelo módulo (`_p.<nome>`), não por import direto —
assim o monkeypatch de testes em `appaiforge.provisioning._docker` (e de outras funções que a
suíte já substitui há tempos) continua funcionando sem mudança nenhuma de teste."""

import json
import logging
import os
import time

import docker

from ..models import ExecutionMode, System
from .base import ComputeUnitNotFound

log = logging.getLogger(__name__)

# uid/gid do usuário não-root da imagem base (ADR 0018) — deve casar com o
# `useradd --uid 1000 --gid agent` de base-image/Dockerfile. Só se aplica a
# sistemas em ExecutionMode.reduced; o modo legacy sobe como root explícito.
AGENT_UID = 1000
AGENT_GID = 1000


def _docker() -> docker.DockerClient:
    from .. import provisioning as _p

    return _p._docker()


class DockerProvisioningDriver:
    """Comportamento idêntico ao que `provisioning.py` tinha antes desta extração."""

    def ensure_ready(self) -> None:
        from .. import provisioning as _p

        client = _docker()
        name = _p.get_settings().docker_network
        try:
            client.networks.get(name)
        except docker.errors.NotFound:
            client.networks.create(name, driver="bridge")

    def provision(self, system: System, *, env: dict[str, str], manifest: list[dict]) -> str:
        from .. import provisioning as _p
        from ..agent_profiles import get_profile

        settings = _p.get_settings()
        profile = get_profile(system.agent_profile)
        client = _docker()
        container_name = _p.system_container_name(system.slug)
        # os sidecars dependem do netns do sistema (`network_mode: container:<id>`,
        # D1) — remover primeiro evita um sidecar órfão apontando pra um
        # container que já não existe mais (achado ao recriar via reconciliação)
        _remove_container_if_exists(client, _p.dbgate_sidecar_name(system.slug))
        _remove_container_if_exists(client, _p.httpsproxy_sidecar_name(system.slug))
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

        limits = {
            "nano_cpus": int(settings.container_cpus * 1e9),
            "mem_limit": f"{settings.container_mem_mb}m",
            "pids_limit": settings.container_pids_limit,
        }
        storage_opt = {"size": f"{settings.container_disk_gb}g"}

        kwargs = {
            # Imagem do agente vem do perfil (etapa 7 do roadmap já previa "uma
            # imagem por agente"); settings.base_image continua sendo a imagem
            # dos sidecars da própria plataforma (dbgate/httpsproxy), que não
            # são o agente e não variam por perfil.
            "image": profile["image"],
            "name": container_name,
            "hostname": container_name,
            "network": settings.docker_network,
            "environment": env,
            "volumes": {
                host_dir: {"bind": "/workspace", "mode": "rw"},
                host_config_slug: {"bind": profile["config_mount_path"], "mode": "ro"},
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
                _p.set_status_message(system.id, "ativo sem quota de disco (driver do host não suporta storage-opt)")
            else:
                raise

        self._provision_dbgate_sidecar(system, container.id, manifest)
        self._provision_httpsproxy_sidecar(system, container.id)
        return container.id

    def remove(self, system: System) -> None:
        from .. import provisioning as _p

        client = _docker()
        for name in (
            _p.dbgate_sidecar_name(system.slug),
            _p.httpsproxy_sidecar_name(system.slug),
            _p.system_container_name(system.slug),
        ):
            try:
                client.containers.get(name).remove(force=True)
            except docker.errors.NotFound:
                pass

    def reconcile_one(self, system_id: str, slug: str) -> None:
        from .. import provisioning as _p

        client = _docker()
        try:
            system_container = client.containers.get(_p.system_container_name(slug))
        except docker.errors.NotFound:
            raise ComputeUnitNotFound(slug) from None
        self._reconcile_dbgate_sidecar(system_id, slug, system_container.id)
        self._reconcile_httpsproxy_sidecar(system_id, slug, system_container.id)

    def refresh_https_allowlist(self, system: System) -> None:
        self._provision_httpsproxy_sidecar(system, system.container_id)

    def publish(self, system: System) -> None:
        from .. import edge

        edge.publish_app_docker(system)

    def unpublish(self, slug: str) -> None:
        from .. import edge

        edge.unpublish_app_docker(slug)

    def healthcheck_url(self, system: System) -> str:
        from .. import provisioning as _p

        return f"http://{_p.system_container_name(system.slug)}:{_p.get_settings().app_port}/"

    def is_healthy(self, slug: str) -> bool:
        """Qualquer resposta HTTP (<500) significa app viva — o gate de identidade responde 403
        sem token, e isso é app no ar, não app caída (mesmo critério de antes desta extração)."""
        import httpx

        from .. import provisioning as _p

        url = f"http://{_p.system_container_name(slug)}:{_p.get_settings().app_port}/"
        try:
            resp = httpx.get(url, timeout=5)
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    # -- sidecars (D1 do design agent-network-perimeter / db-proxy-gate-data-plane) --

    def _provision_dbgate_sidecar(self, system: System, system_container_id: str, manifest: list[dict]) -> None:
        """Sidecar de gate de banco: container próprio, `network_mode: container:<id>` do
        sistema — enxerga o mesmo loopback, mas tem ciclo de vida independente e é o único a
        guardar as credenciais reais das conexões. Sem conexão Postgres/MySQL, não sobe nenhum."""
        from .. import provisioning as _p

        client = _docker()
        name = _p.dbgate_sidecar_name(system.slug)
        _remove_container_if_exists(client, name)
        if not manifest:
            return

        settings = _p.get_settings()
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

    def _provision_httpsproxy_sidecar(self, system: System, system_container_id: str) -> None:
        """Proxy HTTP(S) de saída: container próprio, `network_mode: container:<id>` do sistema
        — mesmo padrão do sidecar de gate de banco. Ao contrário dele, sobe sempre."""
        from .. import provisioning as _p
        from ..services.network_policy import final_https_allowlist

        client = _docker()
        name = _p.httpsproxy_sidecar_name(system.slug)
        _remove_container_if_exists(client, name)

        settings = _p.get_settings()
        allow = final_https_allowlist(system)
        env = {
            "LISTEN_PORT": str(_p.HTTPS_PROXY_PORT),
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

    def _reconcile_dbgate_sidecar(self, system_id: str, slug: str, system_container_id: str) -> None:
        """Sistema presente, mas o sidecar sumiu sozinho (removido manualmente, OOM-killed sem
        restart etc.) — recria só ele, sem derrubar sessões do agente nem o container do sistema."""
        from .. import provisioning as _p

        manifest = _p.db_connections_manifest(system_id)
        if not manifest:
            return
        client = _docker()
        try:
            client.containers.get(_p.dbgate_sidecar_name(slug))
            return
        except docker.errors.NotFound:
            pass
        log.warning("reconciliação: sidecar de gate de banco ausente para %s; recriando", slug)
        from ..services.systems import get_system

        system = get_system(system_id)
        if system is not None:
            self._provision_dbgate_sidecar(system, system_container_id, manifest)

    def _reconcile_httpsproxy_sidecar(self, system_id: str, slug: str, system_container_id: str) -> None:
        """Mesmo racional do `_reconcile_dbgate_sidecar`, pro proxy HTTP(S) de saída — esse sobe
        sempre (nunca condicional a manifesto)."""
        from .. import provisioning as _p

        client = _docker()
        try:
            client.containers.get(_p.httpsproxy_sidecar_name(slug))
            return
        except docker.errors.NotFound:
            pass
        log.warning("reconciliação: sidecar do proxy HTTP(S) ausente para %s; recriando", slug)
        from ..services.systems import get_system

        system = get_system(system_id)
        if system is not None:
            self._provision_httpsproxy_sidecar(system, system_container_id)


def _remove_container_if_exists(client: docker.DockerClient, name: str) -> None:
    """Remoção retry-ável (corridas entre provisionamento, refresh de conexões e reconciliação —
    mesmo padrão do container do sistema)."""
    for _ in range(5):
        try:
            client.containers.get(name).remove(force=True)
            break
        except docker.errors.NotFound:
            break
        except docker.errors.APIError:
            time.sleep(1)


def _execution_identity(mode: ExecutionMode) -> dict:
    """kwargs de identidade de execução do container (ADR 0018, spec container-lifecycle).

    reduced e sandboxed: usuário não-root da imagem, sem capabilities, sem escalada de
    privilégio — sandboxed ganha a camada adicional de seccomp/Landlock dentro do container,
    instalada pelo supervisor (etapa 2, capability agent-sandbox), mas a identidade no
    `docker.containers.run()` é a mesma. legacy: `user="root"` explícito."""
    if mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        return {
            "user": f"{AGENT_UID}:{AGENT_GID}",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
        }
    return {"user": "root"}
