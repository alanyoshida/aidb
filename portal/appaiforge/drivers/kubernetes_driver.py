"""Driver de provisionamento Kubernetes (change `add-kubernetes-driver`, etapa 8 do roadmap de
confinamento; capability `container-driver-kubernetes`). Validado primeiro num cluster `kind`
local — ver `openspec/changes/add-kubernetes-driver/README.md`.

Um Pod por sistema, com três containers (agente + sidecars `dbgate`/`httpsproxy`) compartilhando
o network namespace do Pod por construção — sem a dependência de ordem que o driver Docker tem
hoje (`network_mode: container:<id>` exige o container principal existir primeiro). Workspace via
PVC (persiste entre recriações do Pod); arquivos de config via ConfigMap — não PVC: um PVC do
`local-path-provisioner` fica no filesystem do NÓ do cluster, inacessível ao portal (que roda fora
do cluster) para escrita direta, ao contrário do bind mount do driver Docker (design.md, D3,
achado durante esta implementação)."""

import json
import logging
import os

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

_TRAEFIK_GROUP = "traefik.io"
_TRAEFIK_VERSION = "v1alpha1"

from ..models import ExecutionMode, System
from .base import ComputeUnitNotFound

log = logging.getLogger(__name__)

AGENT_UID = 1000
AGENT_GID = 1000


def _api() -> k8s.CoreV1Api:
    """Carrega o kubeconfig do ambiente (cluster `kind` local nesta etapa — ver README do
    change) uma vez por chamada, mesmo padrão de `_docker()` no driver Docker: nada de cliente
    cacheado em variável de módulo, pra não guardar configuração obsoleta entre testes.

    Sempre com `context` explícito (nunca o `current-context` implícito do kubeconfig) — achado
    real durante a validação: o `current-context` deste host mudou entre dois passos manuais
    desta mesma etapa sem nenhuma ação deste driver, o que faria qualquer chamada sem contexto
    explícito falar com o cluster errado silenciosamente."""
    from .. import provisioning as _p

    k8s_config.load_kube_config(context=_p.get_settings().k8s_kubeconfig_context)
    return k8s.CoreV1Api()


class KubernetesProvisioningDriver:
    def ensure_ready(self) -> None:
        from .. import provisioning as _p

        api = _api()
        name = _p.get_settings().k8s_namespace
        try:
            api.read_namespace(name)
        except ApiException as exc:
            if exc.status == 404:
                api.create_namespace(k8s.V1Namespace(metadata=k8s.V1ObjectMeta(name=name)))
            else:
                raise

    def provision(self, system: System, *, env: dict[str, str], manifest: list[dict]) -> str:
        from .. import provisioning as _p
        from ..agent_profiles import get_profile

        settings = _p.get_settings()
        profile = get_profile(system.agent_profile)
        namespace = settings.k8s_namespace
        name = _p.system_container_name(system.slug)
        api = _api()

        _delete_pod_if_exists(api, namespace, name)
        _ensure_workspace_pvc(api, namespace, system.slug, settings.container_disk_gb)
        _upsert_config_map(api, namespace, system.slug, settings.configs_dir)

        containers = [_agent_container(system, profile, env, settings)]
        if manifest:
            containers.append(_dbgate_container(system, manifest, settings))
        containers.append(_httpsproxy_container(system, settings))

        pod = k8s.V1Pod(
            metadata=k8s.V1ObjectMeta(
                name=name,
                labels={
                    "appaiforge.system_id": system.id,
                    "appaiforge.slug": system.slug,
                    "appaiforge.managed": "true",
                },
            ),
            spec=k8s.V1PodSpec(
                restart_policy="Always",
                security_context=_pod_security_context(system.execution_mode),
                containers=containers,
                volumes=[
                    k8s.V1Volume(
                        name="workspace",
                        persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                            claim_name=_workspace_pvc_name(system.slug)
                        ),
                    ),
                    k8s.V1Volume(
                        name="config",
                        config_map=k8s.V1ConfigMapVolumeSource(name=_config_map_name(system.slug)),
                    ),
                ],
            ),
        )
        created = api.create_namespaced_pod(namespace, pod)
        return created.metadata.uid

    def remove(self, system: System) -> None:
        from .. import provisioning as _p

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(system.slug)
        api = _api()
        _delete_pod_if_exists(api, namespace, name)
        try:
            api.delete_namespaced_config_map(_config_map_name(system.slug), namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
        # o PVC do workspace NÃO é removido aqui — mesma semântica do driver Docker, que
        # preserva o bind mount do workspace ao parar/remover o container (spec
        # container-lifecycle, "Arquivamento preserva workspace"). Exclusão definitiva do
        # workspace é responsabilidade de `delete_system`, agnóstica de driver.

    def reconcile_one(self, system_id: str, slug: str) -> None:
        from .. import provisioning as _p

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(slug)
        api = _api()
        try:
            api.read_namespaced_pod(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise ComputeUnitNotFound(slug) from None
            raise
        # Os sidecars vivem no MESMO Pod que o container do agente — não há "sidecar sumiu mas o
        # Pod continua" como existe no driver Docker (containers independentes). Se o Pod existe,
        # os três containers existem; divergência de container individual dentro do Pod (ex.: um
        # deles em CrashLoopBackOff) é responsabilidade do kubelet via `restartPolicy`, não desta
        # reconciliação.

    def refresh_https_allowlist(self, system: System) -> None:
        """**Limitação conhecida** (design.md, D5-adjacente — achado durante a implementação):
        no driver Docker, isto recria só o sidecar do proxy, sem afetar o container do agente. No
        driver Kubernetes os três containers vivem no mesmo Pod e a env de um container é imutável
        depois de criado — não há como atualizar só `ALLOWED_HOSTS` do sidecar `httpsproxy` sem
        recriar o Pod inteiro. Aceito como lacuna desta etapa (mesma categoria da lacuna de
        `pids_limit`): reaplica via `provision()` completo, o que também reinicia a sessão do
        agente — diferente do driver Docker, onde essa operação é deliberadamente mais leve."""
        from .. import provisioning as _p

        _p.provision_system(system)

    def publish(self, system: System) -> None:
        """Garante Service + Middleware (stripPrefix) + IngressRoute pra `/apps/{slug}` —
        equivalente ao `apps-<slug>.yml` que o driver Docker escreve pro file provider do
        Traefik, só que como objetos nativos do cluster (Traefik roda dentro dele, D4 do
        design), lidos via CRD (`providers.kubernetesCRD`) em vez de arquivo compartilhado."""
        from .. import provisioning as _p

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(system.slug)
        slug = system.slug
        api = _api()

        service = k8s.V1Service(
            metadata=k8s.V1ObjectMeta(name=name),
            spec=k8s.V1ServiceSpec(
                selector={"appaiforge.slug": slug},
                ports=[k8s.V1ServicePort(port=settings.app_port, target_port=settings.app_port)],
            ),
        )
        try:
            api.replace_namespaced_service(name, namespace, service)
        except ApiException as exc:
            if exc.status == 404:
                api.create_namespaced_service(namespace, service)
            else:
                raise

        custom = _custom_api()
        middleware = {
            "apiVersion": f"{_TRAEFIK_GROUP}/{_TRAEFIK_VERSION}",
            "kind": "Middleware",
            "metadata": {"name": f"{name}-strip", "namespace": namespace},
            "spec": {"stripPrefix": {"prefixes": [f"/apps/{slug}"]}},
        }
        _upsert_custom(custom, namespace, "middlewares", f"{name}-strip", middleware)

        ingressroute = {
            "apiVersion": f"{_TRAEFIK_GROUP}/{_TRAEFIK_VERSION}",
            "kind": "IngressRoute",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "entryPoints": ["web"],
                "routes": [
                    {
                        "match": f"PathPrefix(`/apps/{slug}`)",
                        "kind": "Rule",
                        "priority": 100,
                        "middlewares": [{"name": f"{name}-strip"}],
                        "services": [{"name": name, "port": settings.app_port}],
                    }
                ],
            },
        }
        _upsert_custom(custom, namespace, "ingressroutes", name, ingressroute)

    def unpublish(self, slug: str) -> None:
        from .. import provisioning as _p

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(slug)
        api = _api()
        try:
            api.delete_namespaced_service(name, namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise

        custom = _custom_api()
        for plural, object_name in (("ingressroutes", name), ("middlewares", f"{name}-strip")):
            try:
                custom.delete_namespaced_custom_object(
                    _TRAEFIK_GROUP, _TRAEFIK_VERSION, namespace, plural, object_name
                )
            except ApiException as exc:
                if exc.status != 404:
                    raise

    def healthcheck_url(self, system: System) -> str:
        from .. import provisioning as _p

        settings = _p.get_settings()
        name = _p.system_container_name(system.slug)
        return f"http://{name}.{settings.k8s_namespace}.svc.cluster.local:{settings.app_port}/"

    def is_healthy(self, slug: str) -> bool:
        """Lê o resultado da `readinessProbe` do container `agent` via API, em vez de sondar
        HTTP a partir do portal — a rede do Pod só é alcançável de dentro do cluster, e o portal
        roda fora dele por design (k8s_kubeconfig_context). O kubelet, que roda no nó, já faz
        exatamente essa sonda HTTP por dentro; o portal só lê o veredito."""
        from .. import provisioning as _p

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(slug)
        api = _api()
        try:
            pod = api.read_namespaced_pod(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        if pod.status.phase != "Running":
            return False
        statuses = pod.status.container_statuses or []
        agent_status = next((cs for cs in statuses if cs.name == "agent"), None)
        return bool(agent_status and agent_status.ready)


def _custom_api() -> k8s.CustomObjectsApi:
    from .. import provisioning as _p

    k8s_config.load_kube_config(context=_p.get_settings().k8s_kubeconfig_context)
    return k8s.CustomObjectsApi()


def _upsert_custom(custom: k8s.CustomObjectsApi, namespace: str, plural: str, name: str, body: dict) -> None:
    """Cria ou substitui um objeto de CRD do Traefik (Middleware/IngressRoute) — mesmo padrão
    delete-then-create usado pelos containers no driver Docker, aqui adaptado porque objetos de
    CRD precisam de `resourceVersion` pra substituir (então é mais simples apagar e recriar)."""
    from kubernetes.client.rest import ApiException

    try:
        custom.delete_namespaced_custom_object(_TRAEFIK_GROUP, _TRAEFIK_VERSION, namespace, plural, name)
    except ApiException as exc:
        if exc.status != 404:
            raise
    custom.create_namespaced_custom_object(_TRAEFIK_GROUP, _TRAEFIK_VERSION, namespace, plural, body)


def _workspace_pvc_name(slug: str) -> str:
    from .. import provisioning as _p

    return f"{_p.system_container_name(slug)}-workspace"


def _config_map_name(slug: str) -> str:
    from .. import provisioning as _p

    return f"{_p.system_container_name(slug)}-config"


def _delete_pod_if_exists(api: k8s.CoreV1Api, namespace: str, name: str) -> None:
    try:
        api.delete_namespaced_pod(name, namespace, grace_period_seconds=0)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _ensure_workspace_pvc(api: k8s.CoreV1Api, namespace: str, slug: str, disk_gb: int) -> None:
    """Cria o PVC do workspace só se ainda não existir — nunca recriado em cada provision(), pra
    não perder o conteúdo do workspace entre reprovisionamentos (equivalente ao bind mount do
    host persistir entre `docker.containers.run()` sucessivos no driver Docker)."""
    name = _workspace_pvc_name(slug)
    try:
        api.read_namespaced_persistent_volume_claim(name, namespace)
        return
    except ApiException as exc:
        if exc.status != 404:
            raise
    pvc = k8s.V1PersistentVolumeClaim(
        metadata=k8s.V1ObjectMeta(name=name),
        spec=k8s.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=k8s.V1VolumeResourceRequirements(requests={"storage": f"{disk_gb}Gi"}),
        ),
    )
    api.create_namespaced_persistent_volume_claim(namespace, pvc)


def _upsert_config_map(api: k8s.CoreV1Api, namespace: str, slug: str, configs_dir: str) -> None:
    """Lê os arquivos que `provisioning.py` já escreveu em `configs_dir/<slug>` (config_writer +
    write_agent_profile, agnósticos de driver) e os publica como ConfigMap — substitui o papel do
    bind mount `ro` do driver Docker, sem exigir filesystem compartilhado com o cluster."""
    name = _config_map_name(slug)
    source_dir = os.path.join(configs_dir, slug)
    data: dict[str, str] = {}
    if os.path.isdir(source_dir):
        for filename in os.listdir(source_dir):
            path = os.path.join(source_dir, filename)
            if os.path.isfile(path):
                with open(path) as f:
                    data[filename] = f.read()
    try:
        api.delete_namespaced_config_map(name, namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
    config_map = k8s.V1ConfigMap(metadata=k8s.V1ObjectMeta(name=name), data=data)
    api.create_namespaced_config_map(namespace, config_map)


def _pod_security_context(mode: ExecutionMode) -> k8s.V1PodSecurityContext | None:
    """Equivalente ao `user=uid:gid` do driver Docker — `fsGroup` substitui o `os.chown` manual
    do workspace: o kubelet ajusta o grupo do volume montado para o Pod, sem o portal precisar
    tocar o filesystem do PVC (que, ao contrário do bind mount, não é alcançável por ele)."""
    if mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        return k8s.V1PodSecurityContext(run_as_user=AGENT_UID, run_as_group=AGENT_GID, fs_group=AGENT_GID)
    return None  # legacy: root, igual ao driver Docker


def _container_security_context(mode: ExecutionMode) -> k8s.V1SecurityContext | None:
    """Equivalente a `cap_drop`/`no-new-privileges` do driver Docker."""
    if mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        return k8s.V1SecurityContext(
            capabilities=k8s.V1Capabilities(drop=["ALL"]),
            allow_privilege_escalation=False,
        )
    return None


def _resource_requirements(settings) -> k8s.V1ResourceRequirements:
    """Mapeia os limites padrão (cpu/memória/disco) pro Pod — `pids_limit` fica de fora: sem
    equivalente de 1ª classe por container no Kubernetes (limitação conhecida, design.md D5;
    capability container-driver-kubernetes, requirement "Limites de recursos mapeados para o
    Pod")."""
    limits = {
        "cpu": str(settings.container_cpus),
        "memory": f"{settings.container_mem_mb}Mi",
        "ephemeral-storage": f"{settings.container_disk_gb}Gi",
    }
    return k8s.V1ResourceRequirements(limits=limits)


def _agent_container(system: System, profile: dict, env: dict[str, str], settings) -> k8s.V1Container:
    probe = _health_probe(settings.app_port)
    return k8s.V1Container(
        name="agent",
        image=profile["image"],
        env=[k8s.V1EnvVar(name=k, value=v) for k, v in env.items()],
        resources=_resource_requirements(settings),
        security_context=_container_security_context(system.execution_mode),
        readiness_probe=probe,
        liveness_probe=probe,
        volume_mounts=[
            k8s.V1VolumeMount(name="workspace", mount_path="/workspace"),
            k8s.V1VolumeMount(name="config", mount_path=profile["config_mount_path"], read_only=True),
        ],
    )


def _health_probe(app_port: int) -> k8s.V1Probe:
    """Mesmo critério que `health_monitor` usava por HTTP direto do portal (driver Docker):
    qualquer resposta <500 no `app_port` conta como vivo — o gate de identidade responde 403 sem
    token, e isso é app no ar, não app caída. Via `exec`+curl (não `httpGet`) porque o critério
    nativo do kubelet pra `httpGet` só aceita 200–399; perderíamos esse "<500" e quebraria a
    paridade observável com o driver Docker (`test_driver_parity.py`)."""
    check = (
        f'code=$(curl -s -o /dev/null -w "%{{http_code}}" http://127.0.0.1:{app_port}/ 2>/dev/null || echo 000); '
        '[ "$code" != "000" ] && [ "$code" -lt 500 ]'
    )
    return k8s.V1Probe(
        _exec=k8s.V1ExecAction(command=["sh", "-c", check]),
        initial_delay_seconds=10,
        period_seconds=10,
        failure_threshold=3,
    )


def _dbgate_container(system: System, manifest: list[dict], settings) -> k8s.V1Container:
    env = {
        "SYSTEM_ID": system.id,
        "APPAIFORGE_DB_CONNECTIONS": json.dumps(manifest),
        "APPAIFORGE_PORTAL_INTERNAL_URL": settings.portal_internal_url,
        "APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN": settings.db_gate_proxy_service_token,
        "APPAIFORGE_DB_GATE_MODE": settings.db_gate_mode,
    }
    return k8s.V1Container(
        name="dbgate",
        image=settings.base_image,
        command=["python", "/opt/dbproxy/sidecar.py"],
        env=[k8s.V1EnvVar(name=k, value=v) for k, v in env.items()],
    )


def _httpsproxy_container(system: System, settings) -> k8s.V1Container:
    from .. import provisioning as _p
    from ..services.network_policy import final_https_allowlist

    allow = final_https_allowlist(system)
    env = {
        "LISTEN_PORT": str(_p.HTTPS_PROXY_PORT),
        "ALLOWED_HOSTS": json.dumps(allow),
    }
    return k8s.V1Container(
        name="httpsproxy",
        image=settings.base_image,
        command=["python", "/opt/httpproxy/sidecar.py"],
        env=[k8s.V1EnvVar(name=k, value=v) for k, v in env.items()],
    )
