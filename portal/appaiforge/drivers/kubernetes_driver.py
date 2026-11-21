"""Driver de provisionamento Kubernetes (change `add-kubernetes-driver`, etapa 8 do roadmap de
confinamento; capability `container-driver-kubernetes`). Validado primeiro num cluster `kind`
local — ver `openspec/changes/add-kubernetes-driver/README.md`.

Um Pod por sistema, com três containers (agente + sidecars `dbgate`/`httpsproxy`) compartilhando
o network namespace do Pod por construção — sem a dependência de ordem que o driver Docker tem
hoje (`network_mode: container:<id>` exige o container principal existir primeiro). Workspace via
PVC (persiste entre recriações do Pod); arquivos de config via ConfigMap — não PVC: um PVC do
`local-path-provisioner` fica no filesystem do NÓ do cluster, inacessível ao portal (que roda fora
do cluster) para escrita direta, ao contrário do bind mount do driver Docker (design.md, D3,
achado durante esta implementação). D3 resolveu isso para config (ConfigMap via API) mas deixou a
escrita no workspace sem resolução — fechado pela change `fix-k8s-workspace-materialize-delete`:
`write_workspace_files()` escreve no workspace via exec dentro do container do agente (mesmo
mecanismo que `checkpoints._git_via_exec` já usava só para git), e `delete_workspace_pvc()` remove
a PVC na exclusão definitiva do sistema."""

import io
import json
import logging
import os
import tarfile
import time

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

_TRAEFIK_GROUP = "traefik.io"
_TRAEFIK_VERSION = "v1alpha1"

from ..models import ExecutionMode, System
from .base import ComputeUnitNotFound, WorkspaceWriteError

log = logging.getLogger(__name__)

AGENT_UID = 1000
AGENT_GID = 1000

# Container auxiliar de git e onde o PVC do repositório é montado nele (change
# `isolate-workspace-repository`). O repositório fica num subdiretório: a raiz de um PVC pode
# trazer `lost+found`.
GIT_CONTAINER = "git"
GITDIR_MOUNT = "/gitdir"
GIT_DIR = "/gitdir/repo"
GITDIR_PVC_GB = 1

_auth_mode_logged = False


def _load_kube_config() -> None:
    """Autentica com a API do cluster uma vez por chamada (mesmo padrão de `_docker()` no driver
    Docker: nada de cliente cacheado em variável de módulo, pra não guardar configuração obsoleta
    entre testes). Tenta a identidade do próprio Pod primeiro (`ServiceAccount`, quando o portal
    roda dentro do cluster — change `deploy-portal-in-cluster`); cai pro kubeconfig com `context`
    explícito só se isso falhar, preservando sem nenhuma mudança o fluxo de teste manual de fora
    do cluster (host, `k8s_kubeconfig_context`) já validado na etapa anterior.

    Nunca o `current-context` implícito do kubeconfig — achado real durante a etapa anterior: o
    `current-context` deste host mudou entre dois passos manuais sem nenhuma ação deste driver, o
    que faria qualquer chamada sem contexto explícito falar com o cluster errado silenciosamente."""
    global _auth_mode_logged
    from .. import provisioning as _p

    try:
        k8s_config.load_incluster_config()
        mode = "in-cluster (ServiceAccount do Pod)"
    except k8s_config.ConfigException:
        k8s_config.load_kube_config(context=_p.get_settings().k8s_kubeconfig_context)
        mode = "kubeconfig (contexto explícito)"
    if not _auth_mode_logged:
        log.info("driver Kubernetes autenticado via %s", mode)
        _auth_mode_logged = True


def _api() -> k8s.CoreV1Api:
    _load_kube_config()
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
        _ensure_gitdir_pvc(api, namespace, system.slug)
        _upsert_config_map(api, namespace, system.slug, settings.configs_dir)

        containers = [_agent_container(system, profile, env, settings)]
        if manifest:
            containers.append(_dbgate_container(system, manifest, settings))
        containers.append(_httpsproxy_container(system, settings))
        containers.append(_git_container(system, settings))

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
                    # repositório git do sistema, montado SÓ no container `git` (change
                    # `isolate-workspace-repository`, design D2)
                    k8s.V1Volume(
                        name="gitdir",
                        persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                            claim_name=_gitdir_pvc_name(system.slug)
                        ),
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
            pod = api.read_namespaced_pod(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise ComputeUnitNotFound(slug) from None
            raise
        # Pod criado antes do container auxiliar `git` (change `isolate-workspace-repository`):
        # recriado pela reconciliação, como se estivesse ausente — o workspace e o histórico
        # ficam nos PVCs e sobrevivem à recriação.
        if GIT_CONTAINER not in {c.name for c in (pod.spec.containers or [])}:
            raise ComputeUnitNotFound(slug)
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
        design), lidos via CRD (`providers.kubernetesCRD`) em vez de arquivo compartilhado.

        O `Service` também expõe `harness_port` (change `deploy-portal-in-cluster`) — o portal,
        rodando dentro do cluster, alcança o harness do agente pelo DNS deste mesmo `Service`
        (`name`, igual ao hostname que `_harness_url` já monta). Tipo `ClusterIP` (padrão, sem
        `type=`) não é roteável de fora do cluster — só a porta da app é publicada no
        `IngressRoute` abaixo, então a requirement "harness inacessível de fora do cluster"
        continua valendo sem nenhuma mudança adicional."""
        from .. import provisioning as _p
        from ..agent_profiles import get_profile

        settings = _p.get_settings()
        namespace = settings.k8s_namespace
        name = _p.system_container_name(system.slug)
        slug = system.slug
        harness_port = get_profile(system.agent_profile)["harness_port"]
        api = _api()

        service = k8s.V1Service(
            metadata=k8s.V1ObjectMeta(name=name),
            spec=k8s.V1ServiceSpec(
                selector={"appaiforge.slug": slug},
                ports=[
                    k8s.V1ServicePort(name="app", port=settings.app_port, target_port=settings.app_port),
                    k8s.V1ServicePort(name="harness", port=harness_port, target_port=harness_port),
                ],
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
        objects = app_route_objects(namespace, name, slug, settings.app_port)
        for plural, obj in objects:
            _upsert_custom(custom, namespace, plural, obj["metadata"]["name"], obj)

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
        for plural, object_name in (
            ("ingressroutes", name), ("middlewares", f"{name}-strip"), ("middlewares", f"{name}-auth"),
        ):
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


def app_route_objects(namespace: str, name: str, slug: str, app_port: int) -> list[tuple[str, dict]]:
    """Middlewares (forwardAuth + stripPrefix) e IngressRoute de `/apps/{slug}` — equivalentes
    ao `apps-<slug>.yml` do driver Docker (`edge.app_route_config`). O forwardAuth vem ANTES do
    strip (change add-oidc-sso, D8) e chama o portal pelo endereço interno (Service)."""
    from ..edge import EDGE_AUTH_RESPONSE_HEADERS, edge_auth_address

    api_version = f"{_TRAEFIK_GROUP}/{_TRAEFIK_VERSION}"
    auth_mw = {
        "apiVersion": api_version,
        "kind": "Middleware",
        "metadata": {"name": f"{name}-auth", "namespace": namespace},
        "spec": {"forwardAuth": {
            "address": edge_auth_address(slug),
            "authResponseHeaders": list(EDGE_AUTH_RESPONSE_HEADERS),
        }},
    }
    strip_mw = {
        "apiVersion": api_version,
        "kind": "Middleware",
        "metadata": {"name": f"{name}-strip", "namespace": namespace},
        "spec": {"stripPrefix": {"prefixes": [f"/apps/{slug}"]}},
    }
    ingressroute = {
        "apiVersion": api_version,
        "kind": "IngressRoute",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "entryPoints": ["web"],
            "routes": [
                {
                    "match": f"PathPrefix(`/apps/{slug}`)",
                    "kind": "Rule",
                    "priority": 100,
                    "middlewares": [{"name": f"{name}-auth"}, {"name": f"{name}-strip"}],
                    "services": [{"name": name, "port": app_port}],
                }
            ],
        },
    }
    return [("middlewares", auth_mw), ("middlewares", strip_mw), ("ingressroutes", ingressroute)]


def _custom_api() -> k8s.CustomObjectsApi:
    _load_kube_config()
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


def _gitdir_pvc_name(slug: str) -> str:
    from .. import provisioning as _p

    return f"{_p.system_container_name(slug)}-gitdir"


def delete_gitdir_pvc(slug: str, *, timeout: float = 60.0, interval: float = 1.0) -> None:
    """Remove o PVC do repositório git do sistema — só na exclusão definitiva, como o do
    workspace (change `isolate-workspace-repository`)."""
    _delete_pvc_and_wait(_gitdir_pvc_name(slug), timeout=timeout, interval=interval)


def delete_workspace_pvc(slug: str, *, timeout: float = 60.0, interval: float = 1.0) -> None:
    """Remove a PVC do workspace do sistema — chamado só por `provisioning.delete_system`
    (exclusão definitiva, agnóstica de driver; change `fix-k8s-workspace-materialize-delete`).
    `remove()` desta classe (arquivamento/parada) deliberadamente NÃO chama isto, pra preservar o
    workspace entre reprovisionamentos (docstring de `_ensure_workspace_pvc`). 404 é sucesso
    (idempotente), mesmo padrão já usado para o Service e as CRDs do Traefik em `unpublish()`."""
    _delete_pvc_and_wait(_workspace_pvc_name(slug), timeout=timeout, interval=interval)


def _delete_pvc_and_wait(name: str, *, timeout: float, interval: float) -> None:
    from .. import provisioning as _p

    namespace = _p.get_settings().k8s_namespace
    api = _api()
    try:
        api.delete_namespaced_persistent_volume_claim(name, namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
        return
    # A exclusão é assíncrona: o PVC fica com deletionTimestamp + finalizer `pvc-protection` até o
    # Pod que o montava terminar (alguns segundos, medido no kind). Espera sumir para que "exclusão
    # definitiva" tenha o mesmo significado do driver Docker (rmtree síncrono) quando retorna.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            api.read_namespaced_persistent_volume_claim(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        time.sleep(interval)
    raise TimeoutError(f"PVC {namespace}/{name} ainda existe {timeout:.0f}s depois da exclusão")


def _wait_for_agent_container_started(pod_name: str, namespace: str, *, timeout: float = 30.0, interval: float = 1.0) -> None:
    """Aguarda o container `agent` existir e ter iniciado, antes de um exec nele — condição mais
    fraca e mais rápida que `is_healthy()` (que exige a readinessProbe), porque aqui só precisamos
    de um processo pra exec'utar um shell dentro, não da app já respondendo; exigir a readiness
    probe arriscaria um deadlock, já que ela pode depender de arquivos que só chegam via este
    mesmo mecanismo (change `fix-k8s-workspace-materialize-delete`). Levanta `WorkspaceWriteError`
    no timeout em vez de bloquear indefinidamente."""
    api = _api()
    deadline = time.monotonic() + timeout
    while True:
        try:
            pod = api.read_namespaced_pod(pod_name, namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
            pod = None
        if pod is not None:
            statuses = pod.status.container_statuses or []
            agent_status = next((cs for cs in statuses if cs.name == "agent"), None)
            if agent_status is not None and agent_status.started:
                return
            if agent_status is None and pod.status.phase == "Running":
                return
        if time.monotonic() >= deadline:
            raise WorkspaceWriteError(
                f"container 'agent' do Pod {pod_name!r} não iniciou em {timeout}s para exec"
            )
        time.sleep(interval)


def write_workspace_files(system: System, files: dict[str, bytes]) -> None:
    """Escreve `files` (caminho relativo a `/workspace` -> conteúdo) no workspace REAL do
    sistema via exec na API do Kubernetes — generaliza `checkpoints._git_via_exec` (mesmo
    mecanismo, usado lá só para git) para qualquer escrita de arquivo, achado real durante
    `deploy-portal-in-cluster`: `materialize()` não tinha nenhum caminho local válido sob este
    driver (a PVC só é visível de dentro do Pod). Empacota `files` num tar em memória e extrai
    com um só exec (`tar -xf -`), criando subdiretórios (ex.: `portal_templates/`) e gravando
    todos os arquivos numa chamada em vez de uma por arquivo — mesma técnica que `kubectl cp`
    usa. `write_stdin` aceita `bytes` diretamente (frame binário do WebSocket, sem round-trip por
    texto/UTF-8), então o conteúdo do tar não precisa de base64."""
    from kubernetes.stream import stream

    from .. import provisioning as _p
    from ..edge import system_container_name

    settings = _p.get_settings()
    namespace = settings.k8s_namespace
    pod_name = system_container_name(system.slug)
    _wait_for_agent_container_started(pod_name, namespace)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel_path, content in files.items():
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(content)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(content))

    resp = stream(
        _api().connect_get_namespaced_pod_exec,
        pod_name,
        namespace,
        container="agent",
        command=["tar", "-xf", "-", "-C", "/workspace"],
        stderr=True,
        stdin=True,
        stdout=True,
        tty=False,
        _preload_content=False,
    )
    resp.write_stdin(buffer.getvalue())
    resp.run_forever(timeout=60)
    stderr = (resp.read_stderr() or "").strip()
    returncode = resp.returncode
    if returncode not in (0, None):
        raise WorkspaceWriteError(f"tar -xf - -C /workspace: {stderr}")


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


def _ensure_gitdir_pvc(api: k8s.CoreV1Api, namespace: str, slug: str) -> None:
    """PVC do repositório git do sistema, criado uma vez e nunca recriado (mesma regra do PVC do
    workspace). Pequeno: guarda só o histórico do código gerado."""
    name = _gitdir_pvc_name(slug)
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
            resources=k8s.V1VolumeResourceRequirements(requests={"storage": f"{GITDIR_PVC_GB}Gi"}),
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


def _git_container(system: System, settings) -> k8s.V1Container:
    """Container auxiliar onde o portal executa git (change `isolate-workspace-repository`,
    design D2): monta o workspace (árvore de trabalho) e o PVC do repositório, que o container
    `agent` NÃO monta. Fica ocioso; só executa o que o portal pede por exec. Mesma identidade e
    mesmas restrições do container do agente, para os arquivos escritos continuarem dele."""
    return k8s.V1Container(
        name=GIT_CONTAINER,
        image=settings.base_image,
        command=["sleep", "infinity"],
        working_dir="/workspace",
        security_context=_container_security_context(system.execution_mode),
        resources=k8s.V1ResourceRequirements(limits={"cpu": "500m", "memory": "256Mi"}),
        volume_mounts=[
            k8s.V1VolumeMount(name="workspace", mount_path="/workspace"),
            k8s.V1VolumeMount(name="gitdir", mount_path=GITDIR_MOUNT),
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


# ---------------------------------------------------------------------------------------------
# Backend git (change `isolate-workspace-repository`, design D2): todo git do portal roda por
# exec no container auxiliar `git` do pod — nunca no container `agent` —, contra o repositório
# no PVC próprio, com o mesmo ambiente limpo e as mesmas opções do backend Docker.
# ---------------------------------------------------------------------------------------------

# Copia, como dado, só os arquivos de objeto do `.git` antigo do workspace (design D4): `find`
# sem seguir links simbólicos, só arquivos regulares em `xx/` hexadecimais e `pack/pack-*`;
# `objects/info/alternates` e o resto do `.git` antigo nunca são lidos.
_IMPORT_LEGACY_OBJECTS = r"""
old=/workspace/.git; src=/workspace/.git/objects; dst="$1/objects"
[ -d "$old" ] && [ ! -L "$old" ] && [ -d "$src" ] && [ ! -L "$src" ] || exit 0
cd "$src" || exit 0
find . -mindepth 2 -maxdepth 2 -type f | while IFS= read -r f; do
  d=${f%/*}; n=${f##*/}
  case "$d" in
    ./pack) case "$n" in pack-*.pack|pack-*.idx|pack-*.rev) ;; *) continue ;; esac ;;
    ./[0-9a-f][0-9a-f]) case "$n" in *[!0-9a-f]*) continue ;; esac ;;
    *) continue ;;
  esac
  [ -e "$dst/$f" ] && continue
  mkdir -p "$dst/$d" && cp "$f" "$dst/$f" && chmod 444 "$dst/$f"
done
exit 0
"""


def _exec(system: System, container: str, command: list[str], *, timeout: int = 60,
          stdin: bytes | None = None) -> tuple[int, str, str]:
    """Executa `command` num container do pod do sistema e devolve (código, stdout, stderr).
    Pod sem o container pedido (criado antes dele existir) vira `WorkspaceWriteError` com
    mensagem clara, em vez de cair em outro container."""
    from kubernetes.stream import stream

    from .. import provisioning as _p

    namespace = _p.get_settings().k8s_namespace
    pod_name = _p.system_container_name(system.slug)
    try:
        pod = _api().read_namespaced_pod(pod_name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            raise WorkspaceWriteError(f"Pod {pod_name!r} não existe") from None
        raise
    if container not in {c.name for c in (pod.spec.containers or [])}:
        raise WorkspaceWriteError(
            f"Pod {pod_name!r} não tem o container {container!r}; aguarde a reconciliação recriá-lo"
        )
    _wait_for_container_started(pod_name, namespace, container)
    resp = stream(
        _api().connect_get_namespaced_pod_exec,
        pod_name,
        namespace,
        container=container,
        command=command,
        stderr=True,
        stdin=stdin is not None,
        stdout=True,
        tty=False,
        _preload_content=False,
    )
    if stdin is not None:
        # O cliente não sinaliza fim de entrada de forma portável: quem lê consome exatamente
        # len(stdin) bytes (ex.: `head -c`), nunca espera pelo fim do fluxo.
        resp.write_stdin(stdin)
    resp.run_forever(timeout=timeout)
    stdout = resp.read_stdout() or ""
    stderr = resp.read_stderr() or ""
    returncode = resp.returncode
    return (0 if returncode is None else returncode), stdout, stderr


def _wait_for_container_started(pod_name: str, namespace: str, container: str, *, timeout: float = 60.0) -> None:
    api = _api()
    deadline = time.monotonic() + timeout
    while True:
        pod = api.read_namespaced_pod(pod_name, namespace)
        status = next((cs for cs in (pod.status.container_statuses or []) if cs.name == container), None)
        if status is not None and status.started:
            return
        if time.monotonic() >= deadline:
            raise WorkspaceWriteError(f"container {container!r} do Pod {pod_name!r} não iniciou em {timeout}s")
        time.sleep(1)


class KubernetesGitBackend:
    """Implementação Kubernetes de `git_backend.GitBackend`."""

    def _git_command(self, args: tuple[str, ...], work_tree: bool) -> list[str]:
        from ..git_backend import SAFE_OPTIONS, git_env

        env = git_env(GIT_DIR, "/workspace" if work_tree else None)
        return ["env", "-i", *(f"{k}={v}" for k, v in env.items()), "git", *SAFE_OPTIONS, *args]

    def run(self, system: System, *args: str, work_tree: bool = True) -> str:
        from ..git_backend import GitError

        try:
            code, stdout, stderr = _exec(system, GIT_CONTAINER, self._git_command(args, work_tree))
        except WorkspaceWriteError as exc:
            raise GitError(str(exc)) from None
        if code != 0:
            raise GitError(f"git {' '.join(args[:2])}: {stderr.strip()}", code)
        return stdout.strip()

    def _sh(self, system: System, script: str, *argv: str) -> int:
        from ..git_backend import GitError

        try:
            code, _, stderr = _exec(system, GIT_CONTAINER, ["sh", "-c", script, "sh", *argv])
        except WorkspaceWriteError as exc:
            raise GitError(str(exc)) from None
        if code not in (0, 1):
            raise GitError(f"{script.strip().splitlines()[0]}: {stderr.strip()}")
        return code

    def is_initialized(self, system: System) -> bool:
        return self._sh(system, 'test -f "$1/HEAD"', GIT_DIR) == 0

    def create(self, system: System) -> None:
        self._sh(system, 'mkdir -p "$1" && chmod 700 "$1"', GIT_DIR)

    def import_legacy_objects(self, system: System) -> None:
        self._sh(system, _IMPORT_LEGACY_OBJECTS, GIT_DIR)

    def prepare_work_tree(self, system: System) -> None:
        """Nada a fazer: neste driver o git sempre rodou com o uid do agente (exec no pod), então
        o workspace não tem arquivos do root deixados pelo portal."""

    def export_bundle(self, system: System, revs: list[str]) -> bytes:
        """O canal de exec não é seguro para binário: o pacote volta em base64."""
        import base64
        import shlex

        from ..git_backend import GitError

        git = " ".join(shlex.quote(a) for a in self._git_command(("bundle", "create", "-", *revs), False))
        script = f"set -o pipefail 2>/dev/null; {git} | base64 -w0"
        try:
            code, stdout, stderr = _exec(system, GIT_CONTAINER, ["bash", "-c", script], timeout=120)
        except WorkspaceWriteError as exc:
            raise GitError(str(exc)) from None
        if code != 0:
            raise GitError(f"git bundle create: {stderr.strip()}")
        return base64.b64decode(stdout.strip())

    def import_bundle(self, system: System, data: bytes, refspec: str) -> None:
        import base64
        import shlex

        from ..git_backend import BUNDLE_FETCH_OPTIONS, GitError

        bundle = f"{GITDIR_MOUNT}/incoming-{os.getpid()}-{time.monotonic_ns()}.bundle"
        args = ("fetch", "-q", bundle, refspec)
        git = " ".join(shlex.quote(a) for a in self._git_command(args, False))
        # opções de fetch de pacote entram logo depois de "git" e das opções seguras
        git = git.replace(" git ", " git " + " ".join(shlex.quote(o) for o in BUNDLE_FETCH_OPTIONS) + " ", 1)
        encoded = base64.b64encode(data)
        script = (f"head -c {len(encoded)} | base64 -d > {bundle} && {git}; "
                  f"rc=$?; rm -f {bundle}; exit $rc")
        try:
            code, _, stderr = _exec(system, GIT_CONTAINER, ["sh", "-c", script], timeout=120,
                                    stdin=encoded)
        except WorkspaceWriteError as exc:
            raise GitError(str(exc)) from None
        if code != 0:
            raise GitError(f"git fetch (pacote): {stderr.strip()}")

    def add_exclude(self, system: System, pattern: str) -> None:
        self._sh(system, 'mkdir -p "$1/info" && (grep -qxF "$2" "$1/info/exclude" 2>/dev/null || echo "$2" >> "$1/info/exclude")',
                 GIT_DIR, pattern)

    def remove(self, system: System) -> None:
        delete_gitdir_pvc(system.slug)
