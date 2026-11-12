"""Ponta a ponta do driver Kubernetes (change `add-kubernetes-driver`, task 8.3) — mesmo
critério da etapa 7 (`test_claude_code_e2e.py`): Pod real, shim real, CLI `claude` real dentro
do Pod real, `ClaudeCodeHarness` real, `AgentQueue`/checkpoint reais (o mesmo caminho de produção
que um sistema real usaria, só trocando o driver Docker pelo Kubernetes). A única parte
fabricada é o backend do modelo (stub `fake_anthropic.js`, mesmo racional da etapa 7), rodando
como um Pod próprio dentro do cluster — não na rede Docker, porque o Pod do sistema só alcança
o que estiver dentro do cluster (capability `container-driver-kubernetes`).

Diferença real em relação à etapa 7: o processo de teste roda no HOST, fora do cluster, e a
porta do harness não é alcançável de fora por design (task 5.2 desta mesma change) — por isso
usa `kubectl port-forward` em vez de conectar direto no IP do Pod."""

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
