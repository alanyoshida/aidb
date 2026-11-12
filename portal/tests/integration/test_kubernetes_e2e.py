"""Ponta a ponta do driver Kubernetes (change `add-kubernetes-driver`, task 8.3) — mesmo
critério da etapa 7 (`test_claude_code_e2e.py`): Pod real, shim real, CLI `claude` real dentro
do Pod real, `ClaudeCodeHarness` real, `AgentQueue`/checkpoint reais (o mesmo caminho de produção
que um sistema real usaria, só trocando o driver Docker pelo Kubernetes). A única parte
fabricada é o backend do modelo (stub `fake_anthropic.js`, mesmo racional da etapa 7), rodando
como um Pod próprio dentro do cluster — não na rede Docker, porque o Pod do sistema só alcança
o que estiver dentro do cluster (capability `container-driver-kubernetes`).

Diferença real em relação à etapa 7: o processo de teste roda no HOST, fora do cluster, e a
porta do harness não é alcançável de fora por design (task 5.2 desta mesma change) — por isso
usa `kubectl port-forward` em vez de conectar direto no IP do Pod.

`test_sistema_k8s_ponta_a_ponta_com_portal_dentro_do_cluster` (change `deploy-portal-in-cluster`,
task 5.1) cobre o caminho real sem esse port-forward: exercita o MESMO roteiro, mas com o código
executando de dentro do Pod real do portal (`appaiforge-portal`, namespace `appaiforge`,
manifesto `openspec/changes/deploy-portal-in-cluster/portal-deployment.yaml`) — `_harness_url`
sem nenhum monkeypatch, resolvendo pelo DNS do `Service` que `publish()` já cria. Pula se esse
Deployment real não estiver aplicado (é infraestrutura de sessão de validação, não algo que a
suíte sobe por si)."""

import os
import subprocess
import time

import pytest

pytestmark = [pytest.mark.integration]

try:
    from kubernetes import config as k8s_config

    k8s_config.load_kube_config(context="kind-appaiforge-dev")
    _KIND_AVAILABLE = True
except Exception:
    _KIND_AVAILABLE = False

pytestmark.append(pytest.mark.skipif(not _KIND_AVAILABLE, reason="cluster kind-appaiforge-dev indisponível"))

NAMESPACE = "appaiforge-test"
STUB_PORT = 18080
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _k8s_api():
    from kubernetes import client as k8s

    return k8s.CoreV1Api()


@pytest.fixture()
def k8s_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "kubernetes")
    monkeypatch.setenv("APPAIFORGE_K8S_NAMESPACE", NAMESPACE)
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def fake_anthropic_stub_k8s():
    """Stub da Anthropic Messages API como Pod+Service dentro do cluster — o Pod do sistema só
    alcança destinos dentro do cluster (capability container-driver-kubernetes), diferente da
    rede Docker compartilhada que a etapa 7 usava."""
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    api = _k8s_api()
    name = f"fake-anthropic-stub-{os.urandom(4).hex()}"

    with open(os.path.join(FIXTURES_DIR, "fake_anthropic.js")) as f:
        script = f.read()

    config_map = k8s.V1ConfigMap(metadata=k8s.V1ObjectMeta(name=name), data={"fake_anthropic.js": script})
    api.create_namespaced_config_map(NAMESPACE, config_map)

    pod = k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(name=name, labels={"app": name}),
        spec=k8s.V1PodSpec(
            restart_policy="Never",
            containers=[
                k8s.V1Container(
                    name="stub",
                    image="node:22-slim",
                    command=["node", "/fixtures/fake_anthropic.js", str(STUB_PORT)],
                    env=[k8s.V1EnvVar(name="SPIKE_BASH_COMMAND", value="echo e2e-ok > e2e_marker.txt")],
                    volume_mounts=[k8s.V1VolumeMount(name="fixtures", mount_path="/fixtures")],
                )
            ],
            volumes=[k8s.V1Volume(name="fixtures", config_map=k8s.V1ConfigMapVolumeSource(name=name))],
        ),
    )
    api.create_namespaced_pod(NAMESPACE, pod)

    service = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=name),
        spec=k8s.V1ServiceSpec(selector={"app": name}, ports=[k8s.V1ServicePort(port=STUB_PORT, target_port=STUB_PORT)]),
    )
    api.create_namespaced_service(NAMESPACE, service)

    deadline = time.time() + 60
    while time.time() < deadline:
        p = api.read_namespaced_pod(name, NAMESPACE)
        if p.status.phase == "Running" and p.status.container_statuses and p.status.container_statuses[0].ready:
            break
        time.sleep(1)
    else:
        pytest.fail("stub fake_anthropic não ficou Running a tempo")

    url = f"http://{name}.{NAMESPACE}.svc.cluster.local:{STUB_PORT}"
    try:
        yield url
    finally:
        for delete, resource in (
            (lambda n: api.delete_namespaced_pod(n, NAMESPACE, grace_period_seconds=0), name),
            (lambda n: api.delete_namespaced_service(n, NAMESPACE), name),
            (lambda n: api.delete_namespaced_config_map(n, NAMESPACE), name),
        ):
            try:
                delete(resource)
            except ApiException as exc:
                if exc.status != 404:
                    raise


@pytest.fixture()
def k8s_e2e_system(k8s_env, clean_db, fake_anthropic_stub_k8s, monkeypatch):
    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_URL", fake_anthropic_stub_k8s)
    get_settings.cache_clear()

    catalog.ensure_presets()
    editor = auth.create_user("e2e-k8s@t.local", "pw", UserType.editor.value)
    sys = create_system(
        editor, "Sistema E2E K8s", f"e2e-k8s-{os.urandom(3).hex()}",
        agent_profile="claude-code", provider="anthropic",
    )
    yield sys, editor
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _config_map_name, _workspace_pvc_name
    from appaiforge.edge import system_container_name

    api = _k8s_api()
    name = system_container_name(sys.slug)
    for delete, resource in (
        (lambda n: api.delete_namespaced_pod(n, NAMESPACE, grace_period_seconds=0), name),
        (lambda n: api.delete_namespaced_config_map(n, NAMESPACE), _config_map_name(sys.slug)),
        (lambda n: api.delete_namespaced_persistent_volume_claim(n, NAMESPACE), _workspace_pvc_name(sys.slug)),
        (lambda n: api.delete_namespaced_service(n, NAMESPACE), name),
    ):
        try:
            delete(resource)
        except ApiException as exc:
            if exc.status != 404:
                raise
    from kubernetes import client as k8s

    custom = k8s.CustomObjectsApi()
    for plural, obj_name in (("ingressroutes", name), ("middlewares", f"{name}-strip")):
        try:
            custom.delete_namespaced_custom_object("traefik.io", "v1alpha1", NAMESPACE, plural, obj_name)
        except ApiException as exc:
            if exc.status != 404:
                raise
    get_settings.cache_clear()


def _wait_shim_ready(base_url: str, timeout: float = 30.0) -> None:
    import httpx

    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            httpx.post(f"{base_url}/session", timeout=2.0).raise_for_status()
            return
        except Exception as exc:  # noqa: BLE001 — só pra decidir tentar de novo
            last_exc = exc
            time.sleep(0.5)
    raise TimeoutError(f"shim claude-code não respondeu em {timeout}s: {last_exc}")


def _wait_run(queue, run_id: str, timeout: float = 60.0):
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, RunStatus

    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run and run.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
                return run.status, run.summary
        time.sleep(0.3)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


def test_sistema_k8s_ponta_a_ponta_com_checkpoint(k8s_e2e_system, monkeypatch):
    """Mesmo roteiro de `test_sistema_claude_code_ponta_a_ponta_com_checkpoint` (etapa 7), com
    o driver Kubernetes no lugar do Docker: criação → provisionamento real (Pod) → execução real
    do agente contra o stub → checkpoint real (via exec) → marcador real no workspace (via PVC,
    verificado por exec, não por path local)."""
    import appaiforge.agent_queue as agent_queue_module
    from appaiforge.agent_profiles import get_profile
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.checkpoints import list_checkpoints
    from appaiforge.harness.opencode import OpencodeHarness
    from appaiforge.models import RunStatus
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    system, editor = k8s_e2e_system
    provision_system(system)
    pod_name = system_container_name(system.slug)

    for _ in range(30):
        pod = _k8s_api().read_namespaced_pod(pod_name, NAMESPACE)
        if pod.status.phase == "Running" and pod.status.container_statuses and all(
            cs.ready for cs in pod.status.container_statuses
        ):
            break
        time.sleep(1)
    else:
        pytest.fail("Pod do sistema E2E não ficou Running/Ready a tempo")

    profile = get_profile(system.agent_profile)
    local_port = 28091
    port_forward = subprocess.Popen(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", NAMESPACE,
            "port-forward", f"pod/{pod_name}", f"{local_port}:{profile['harness_port']}",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 15
        ready = False
        while time.time() < deadline:
            line = port_forward.stdout.readline()
            if "Forwarding from" in line:
                ready = True
                break
            if port_forward.poll() is not None:
                break
        assert ready, "kubectl port-forward não anunciou pronto a tempo"

        base_url = f"http://127.0.0.1:{local_port}"
        _wait_shim_ready(base_url)

        monkeypatch.setattr(agent_queue_module, "_harness_url", lambda _sys: base_url)
        queue = AgentQueue(OpencodeHarness(agent_queue_module._harness_url))
        run = queue.enqueue(system.id, editor.id, "registre que terminamos o teste", chat_session_id=None)
        status, summary = _wait_run(queue, run.id)

        assert status == RunStatus.succeeded, f"run falhou: {summary}"

        # o checkpoint é criado de forma assíncrona, depois que `_wait_run` já viu o status
        # terminal (agent_queue.py cria o checkpoint DEPOIS de marcar a run como succeeded) —
        # cada chamada git do driver Kubernetes é um round-trip de exec via API, mais lento que
        # o subprocess local do driver Docker, então a corrida é bem mais visível aqui.
        checkpoints = []
        for _ in range(20):
            checkpoints = list_checkpoints(system)
            if checkpoints:
                break
            time.sleep(1)
        assert len(checkpoints) == 1
        assert checkpoints[0]["git_sha"]

        marker = subprocess.run(
            [
                "kubectl", "--context", "kind-appaiforge-dev", "-n", NAMESPACE,
                "exec", pod_name, "-c", "agent", "--", "cat", "/workspace/e2e_marker.txt",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert marker.returncode == 0, f"stdout={marker.stdout!r} stderr={marker.stderr!r}"
        assert marker.stdout.strip() == "e2e-ok"
    finally:
        port_forward.terminate()
        port_forward.wait(timeout=10)


PORTAL_NAMESPACE = "appaiforge"

_PORTAL_REAL_SCRIPT = '''
import os
import time

os.environ["APPAIFORGE_INFERENCE_BROKER_ENABLED"] = "true"
os.environ["APPAIFORGE_INFERENCE_BROKER_URL"] = os.environ["FAKE_ANTHROPIC_URL"]

from appaiforge.config import get_settings
get_settings.cache_clear()

from appaiforge import auth
from appaiforge.agent_queue import get_queue
from appaiforge.checkpoints import list_checkpoints
from appaiforge.db import session_scope
from appaiforge.edge import publish_app, system_container_name
from appaiforge.models import AgentRun, RunStatus, UserType
from appaiforge.provisioning import provision_system
from appaiforge.services import catalog
from appaiforge.services.systems import create_system
from kubernetes import client as k8s

catalog.ensure_presets()
editor = auth.create_user(f"e2e-incluster-{os.urandom(3).hex()}@t.local", "pw", UserType.editor.value)
system = create_system(
    editor, "E2E portal em cluster", f"e2e-incluster-{os.urandom(3).hex()}",
    agent_profile="claude-code", provider="anthropic",
)
print("SLUG:" + system.slug)

provision_system(system)
publish_app(system)
pod_name = system_container_name(system.slug)

api = k8s.CoreV1Api()
for _ in range(60):
    pod = api.read_namespaced_pod(pod_name, os.environ["APPAIFORGE_K8S_NAMESPACE"])
    if pod.status.phase == "Running" and pod.status.container_statuses and all(
        cs.ready for cs in pod.status.container_statuses
    ):
        break
    time.sleep(1)
else:
    raise SystemExit("Pod do sistema nao ficou Running/Ready a tempo")

# SEM monkeypatch de _harness_url -- get_queue() usa o `_harness_url` real
# (agent_queue.py:712), que resolve pelo DNS do Service criado em publish().
queue = get_queue()
run = queue.enqueue(system.id, editor.id, "registre que terminamos o teste", chat_session_id=None)

deadline = time.time() + 90
status = None
while time.time() < deadline:
    with session_scope() as s:
        row = s.get(AgentRun, run.id)
        if row and row.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
            status = row.status
            break
    time.sleep(0.5)
assert status == RunStatus.succeeded, f"run nao terminou com sucesso: {status}"

checkpoints = []
for _ in range(20):
    checkpoints = list_checkpoints(system)
    if checkpoints:
        break
    time.sleep(1)
assert len(checkpoints) == 1, f"esperava 1 checkpoint, achei {len(checkpoints)}"
assert checkpoints[0]["git_sha"]

# Nao apaga a linha do sistema/usuario do Postgres real: `delete_system()` em produção
# (provisioning.py) tambem nunca apaga -- so para/remove o container/workspace, retendo
# systems/checkpoints/runs para auditoria por design. O teste segue a mesma convencao; só os
# objetos do cluster (Pod/PVC/ConfigMap/Service/IngressRoute) sao limpos, abaixo.
print("OK")
'''


@pytest.fixture()
def _portal_real_disponivel():
    """`appaiforge-portal` (Deployment real dentro do cluster, change `deploy-portal-in-cluster`,
    tasks 3.2/4.1-4.2) é infraestrutura de sessão de validação, aplicada manualmente seguindo o
    README do change — esta suíte nunca sobe isso por si (ao contrário do cluster `kind` em si,
    que `_KIND_AVAILABLE` já cobre)."""
    try:
        pod = _k8s_api().list_namespaced_pod(PORTAL_NAMESPACE, label_selector="app=appaiforge-portal").items
    except Exception:
        pod = []
    if not pod or pod[0].status.phase != "Running":
        pytest.skip("Deployment real appaiforge-portal não está aplicado neste cluster (ver README do change)")
    return pod[0].metadata.name


def test_sistema_k8s_ponta_a_ponta_com_portal_dentro_do_cluster(_portal_real_disponivel):
    """Requirement 'Portal alcança o harness de cada sistema pela rede interna do cluster' +
    'Chat com o agente funciona igual nos dois drivers' (change `deploy-portal-in-cluster`) — o
    MESMO roteiro de `test_sistema_k8s_ponta_a_ponta_com_checkpoint`, mas executado de dentro do
    Pod real do portal, sem `kubectl port-forward` e sem nenhum monkeypatch de `_harness_url`."""
    import tempfile

    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    portal_pod = _portal_real_disponivel
    api = _k8s_api()
    stub_name = f"fake-anthropic-incluster-{os.urandom(4).hex()}"

    with open(os.path.join(FIXTURES_DIR, "fake_anthropic.js")) as f:
        stub_script = f.read()

    api.create_namespaced_config_map(
        PORTAL_NAMESPACE, k8s.V1ConfigMap(metadata=k8s.V1ObjectMeta(name=stub_name), data={"fake_anthropic.js": stub_script})
    )
    api.create_namespaced_pod(
        PORTAL_NAMESPACE,
        k8s.V1Pod(
            metadata=k8s.V1ObjectMeta(name=stub_name, labels={"app": stub_name}),
            spec=k8s.V1PodSpec(
                restart_policy="Never",
                containers=[
                    k8s.V1Container(
                        name="stub", image="node:22-slim",
                        command=["node", "/fixtures/fake_anthropic.js", str(STUB_PORT)],
                        env=[k8s.V1EnvVar(name="SPIKE_BASH_COMMAND", value="echo e2e-ok > e2e_marker.txt")],
                        volume_mounts=[k8s.V1VolumeMount(name="fixtures", mount_path="/fixtures")],
                    )
                ],
                volumes=[k8s.V1Volume(name="fixtures", config_map=k8s.V1ConfigMapVolumeSource(name=stub_name))],
            ),
        ),
    )
    api.create_namespaced_service(
        PORTAL_NAMESPACE,
        k8s.V1Service(
            metadata=k8s.V1ObjectMeta(name=stub_name),
            spec=k8s.V1ServiceSpec(selector={"app": stub_name}, ports=[k8s.V1ServicePort(port=STUB_PORT, target_port=STUB_PORT)]),
        ),
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        p = api.read_namespaced_pod(stub_name, PORTAL_NAMESPACE)
        if p.status.phase == "Running" and p.status.container_statuses and p.status.container_statuses[0].ready:
            break
        time.sleep(1)
    else:
        pytest.fail("stub fake_anthropic não ficou Running a tempo")

    slug = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(_PORTAL_REAL_SCRIPT)
            script_path = f.name
        try:
            subprocess.run(
                ["kubectl", "--context", "kind-appaiforge-dev", "-n", PORTAL_NAMESPACE,
                 "cp", script_path, f"{portal_pod}:/tmp/_e2e_incluster.py"],
                capture_output=True, text=True, timeout=30, check=True,
            )
        finally:
            os.unlink(script_path)

        result = subprocess.run(
            ["kubectl", "--context", "kind-appaiforge-dev", "-n", PORTAL_NAMESPACE, "exec", portal_pod, "--",
             "env", f"FAKE_ANTHROPIC_URL=http://{stub_name}:{STUB_PORT}",
             "python", "/tmp/_e2e_incluster.py"],
            capture_output=True, text=True, timeout=150,
        )
        for line in result.stdout.splitlines():
            if line.startswith("SLUG:"):
                slug = line[len("SLUG:"):]
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "OK" in result.stdout
    finally:
        for delete, resource in (
            (lambda n: api.delete_namespaced_pod(n, PORTAL_NAMESPACE, grace_period_seconds=0), stub_name),
            (lambda n: api.delete_namespaced_service(n, PORTAL_NAMESPACE), stub_name),
            (lambda n: api.delete_namespaced_config_map(n, PORTAL_NAMESPACE), stub_name),
        ):
            try:
                delete(resource)
            except ApiException as exc:
                if exc.status != 404:
                    raise
        if slug:
            sys_name = f"appaiforge-sys-{slug}"
            from appaiforge.drivers.kubernetes_driver import _config_map_name, _workspace_pvc_name

            for delete, resource in (
                (lambda n: api.delete_namespaced_pod(n, PORTAL_NAMESPACE, grace_period_seconds=0), sys_name),
                (lambda n: api.delete_namespaced_config_map(n, PORTAL_NAMESPACE), _config_map_name(slug)),
                (lambda n: api.delete_namespaced_persistent_volume_claim(n, PORTAL_NAMESPACE), _workspace_pvc_name(slug)),
                (lambda n: api.delete_namespaced_service(n, PORTAL_NAMESPACE), sys_name),
            ):
                try:
                    delete(resource)
                except ApiException as exc:
                    if exc.status != 404:
                        raise
            custom = k8s.CustomObjectsApi()
            for plural, obj_name in (("ingressroutes", sys_name), ("middlewares", f"{sys_name}-strip")):
                try:
                    custom.delete_namespaced_custom_object("traefik.io", "v1alpha1", PORTAL_NAMESPACE, plural, obj_name)
                except ApiException as exc:
                    if exc.status != 404:
                        raise
