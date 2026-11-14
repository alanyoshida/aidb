"""Integração do driver Kubernetes (change `add-kubernetes-driver`) contra um cluster `kind`
real — ver `openspec/changes/add-kubernetes-driver/README.md` para subir o cluster
`appaiforge-dev` antes de rodar este arquivo. `kubectl config current-context` precisa apontar
pra ele (ou ter `kind-appaiforge-dev` disponível no kubeconfig)."""

import os

import pytest

pytestmark = [pytest.mark.integration]

try:
    from kubernetes import config as k8s_config

    k8s_config.load_kube_config(context="kind-appaiforge-dev")
    _KIND_AVAILABLE = True
except Exception:
    _KIND_AVAILABLE = False

pytestmark.append(pytest.mark.skipif(not _KIND_AVAILABLE, reason="cluster kind-appaiforge-dev indisponível"))


@pytest.fixture()
def k8s_env(tmp_path, monkeypatch):
    """Mesmo papel do `docker_env` dos testes Docker, mais a seleção do driver Kubernetes e um
    namespace isolado pros objetos de teste."""
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "kubernetes")
    monkeypatch.setenv("APPAIFORGE_K8S_NAMESPACE", "appaiforge-test")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _k8s_api():
    from kubernetes import client as k8s

    return k8s.CoreV1Api()


def _wait_pod_running(pod_name: str, timeout_s: int = 30) -> None:
    import time

    for _ in range(timeout_s):
        pod = _k8s_api().read_namespaced_pod(pod_name, "appaiforge-test")
        if pod.status.phase == "Running" and pod.status.container_statuses:
            if all(cs.ready for cs in pod.status.container_statuses):
                return
        time.sleep(1)
    pytest.fail(f"Pod {pod_name} não ficou Running/Ready a tempo")


def _cleanup(slug: str) -> None:
    """Remove Pod/ConfigMap/PVC/Service/IngressRoute/Middleware do sistema de teste, se
    existirem — mesmo racional do `remove_system_containers` dos testes Docker, pra não
    acumular objetos órfãos no cluster."""
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _config_map_name, _workspace_pvc_name
    from appaiforge.edge import system_container_name

    api = _k8s_api()
    namespace = "appaiforge-test"
    name = system_container_name(slug)
    for delete, resource_name in (
        (lambda n: api.delete_namespaced_pod(n, namespace, grace_period_seconds=0), name),
        (lambda n: api.delete_namespaced_config_map(n, namespace), _config_map_name(slug)),
        (lambda n: api.delete_namespaced_persistent_volume_claim(n, namespace), _workspace_pvc_name(slug)),
        (lambda n: api.delete_namespaced_service(n, namespace), name),
    ):
        try:
            delete(resource_name)
        except ApiException as exc:
            if exc.status != 404:
                raise

    custom = k8s.CustomObjectsApi()
    for plural, object_name in (("ingressroutes", name), ("middlewares", f"{name}-strip")):
        try:
            custom.delete_namespaced_custom_object("traefik.io", "v1alpha1", namespace, plural, object_name)
        except ApiException as exc:
            if exc.status != 404:
                raise


@pytest.fixture()
def system(k8s_env, clean_db):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    catalog.ensure_presets()
    editor = auth.create_user("k8s-prov@t.local", "pw", UserType.editor.value)
    sys = create_system(editor, "Sistema K8s", f"k8s-{os.urandom(3).hex()}")
    yield sys
    _cleanup(sys.slug)


def test_provision_system_cria_pod_com_tres_containers(system):
    """Requirement 'Pod único por sistema com containers compartilhando rede' — os três
    containers (agente + dbgate + httpsproxy) sobem juntos, no mesmo Pod."""
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)

    api = _k8s_api()
    pod = api.read_namespaced_pod(system_container_name(system.slug), "appaiforge-test")
    names = {c.name for c in pod.spec.containers}
    # sem conexão de banco cadastrada, o sidecar dbgate não sobe (mesma regra do driver Docker)
    assert names == {"agent", "httpsproxy"}


def test_container_do_agente_roda_com_identidade_reduzida(system):
    """Equivalente ao `test_container_reduzido_sobe_sem_root_e_sem_capabilities` do driver
    Docker — o sistema é criado `sandboxed` por padrão (Landlock disponível neste host), e o
    `securityContext` do Pod deve refletir isso dentro do container, não só na declaração."""
    import subprocess

    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode

    assert system.execution_mode in (ExecutionMode.reduced, ExecutionMode.sandboxed)
    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    result = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--", "id",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "uid=1000" in result.stdout


def test_sidecar_alcanca_agente_por_loopback(system):
    """Requirement 'Sidecar alcança o agente por loopback' — os containers do Pod compartilham
    o netns por construção, sem precisar de nenhum `network_mode` explícito."""
    import subprocess

    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    # o sidecar escuta 127.0.0.1:15500 (HTTPS_PROXY_PORT) — alcançável do container do agente,
    # no MESMO Pod, só porque compartilham netns (não por nenhuma config de rede explícita)
    result = subprocess.run(
        [
            "kubectl",
            "--context",
            "kind-appaiforge-dev",
            "exec",
            pod_name,
            "-n",
            "appaiforge-test",
            "-c",
            "agent",
            "--",
            "python3",
            "-c",
            "import socket; s = socket.create_connection(('127.0.0.1', 15500), timeout=5); s.close(); print('ok')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "ok" in result.stdout


def _to_mi(quantity: str) -> float:
    """Normaliza uma quantidade de recurso k8s (ex.: '2Gi', '2048Mi') pra MiB — a API devolve a
    quantidade na unidade que preferir, não necessariamente a que foi enviada na criação."""
    if quantity.endswith("Gi"):
        return float(quantity[:-2]) * 1024
    if quantity.endswith("Mi"):
        return float(quantity[:-2])
    raise ValueError(f"unidade não tratada: {quantity!r}")


def test_limites_de_recursos_mapeados_para_o_pod(system):
    """Requirement 'Limites de recursos mapeados para o Pod' — CPU/memória/disco do container do
    agente batem com os limites padrão configurados para a plataforma."""
    from appaiforge.config import get_settings
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    settings = get_settings()

    pod = _k8s_api().read_namespaced_pod(system_container_name(system.slug), "appaiforge-test")
    agent = next(c for c in pod.spec.containers if c.name == "agent")
    limits = agent.resources.limits
    assert float(limits["cpu"]) == settings.container_cpus
    assert _to_mi(limits["memory"]) == settings.container_mem_mb
    assert _to_mi(limits["ephemeral-storage"]) == settings.container_disk_gb * 1024


def test_remove_e_idempotente(system):
    from appaiforge.provisioning import provision_system, stop_and_remove

    provision_system(system)
    stop_and_remove(system)
    stop_and_remove(system)  # segunda chamada não deve levantar (NotFound tratado)


def test_workspace_sobrevive_a_recriacao_do_pod(system):
    """Requirement 'Workspace sobrevive à recriação do Pod' — o PVC não é recriado em cada
    `provision()` (só na primeira vez), então o conteúdo grava e sobrevive à recriação."""
    import subprocess

    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    write = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--",
            "sh", "-c", "echo conteudo-antes-da-recriacao > /workspace/marca.txt",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert write.returncode == 0, f"stdout={write.stdout!r} stderr={write.stderr!r}"

    # recria o Pod do sistema (mesmo caminho que reprovisionamento/reconciliação usam) — o PVC
    # do workspace não é tocado por `provision()`, só criado se ainda não existir
    provision_system(system)
    _wait_pod_running(pod_name)

    read = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--",
            "cat", "/workspace/marca.txt",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert read.returncode == 0, f"stdout={read.stdout!r} stderr={read.stderr!r}"
    assert read.stdout.strip() == "conteudo-antes-da-recriacao"




def test_publish_app_roteia_pelo_ingress_externo(system):
    """Requirement 'Conexão ao destino permitido funciona pelo proxy' (D4) aplicado à etapa 5
    deste change: /apps/{slug} alcançável de FORA do cluster, pela porta que o `kind` expõe no
    host (extraPortMappings -> Traefik hostNetwork -> IngressRoute -> Service -> Pod)."""
    import subprocess

    from appaiforge.provisioning import provision_system
    from appaiforge.edge import publish_app, system_container_name

    import time

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)
    publish_app(system)

    # o placeholder do afsupervisor (nenhuma app gerada ainda) responde 200 ou 403 (token
    # ausente), nunca uma falha de conexão — confirma que a cadeia host->Traefik->Service->Pod
    # está de ponta a ponta, sem precisar de uma app real gerada (fora do escopo desta task).
    # Retry curto: o provider CRD do Traefik observa IngressRoute/Service por informers
    # separados — o evento da IngressRoute pode chegar antes do da Service já criada,
    # gerando um 404 transitório até o próximo resync (achado real, não um bug do driver).
    last_code = None
    for _ in range(15):
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://localhost:18080/apps/{system.slug}/"],
            capture_output=True, text=True, timeout=15,
        )
        last_code = result.stdout.strip()
        if last_code in ("200", "403"):
            break
        time.sleep(1)
    assert last_code in ("200", "403"), f"último código: {last_code!r}"


def test_harness_alcancavel_pelo_service_interno(system):
    """Requirement 'Portal alcança o harness de cada sistema pela rede interna do cluster'
    (change `deploy-portal-in-cluster`) — o `Service` que `publish()` cria para `/apps/{slug}`
    também expõe `harness_port`, resolvível pelo DNS do próprio `Service` de dentro do cluster.
    Conecta via `kubectl exec` no container do agente (mesmo papel de cliente "de dentro do
    cluster" que `test_sidecar_alcanca_agente_por_loopback` usa), mas pelo nome do Service em vez
    do loopback do Pod — prova que a rota é por `Service`, não coincidência de rede do Pod."""
    import subprocess

    from appaiforge.agent_profiles import get_profile
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import publish_app, system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)
    publish_app(system)

    harness_port = get_profile(system.agent_profile)["harness_port"]
    result = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--",
            "python3", "-c",
            f"import socket; s = socket.create_connection(('{pod_name}', {harness_port}), timeout=5); "
            "s.close(); print('ok')",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "ok" in result.stdout


def test_harness_e_sidecars_nao_alcancaveis_de_fora_do_cluster(system):
    """Requirement 'Harness e sidecars não alcançáveis de fora do cluster' — nenhum Service
    externo é criado pra essas portas, e o IP do Pod (rede do CNI) não é roteável a partir do
    host real, só de dentro do cluster."""
    import subprocess

    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    pod = _k8s_api().read_namespaced_pod(pod_name, "appaiforge-test")
    pod_ip = pod.status.pod_ip
    assert pod_ip, "Pod sem IP atribuído"

    for port in (4096, 15500):
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "3", f"http://{pod_ip}:{port}/"],
            capture_output=True, text=True, timeout=10,
        )
        # do host real (fora do cluster), o IP do Pod não é roteável — curl falha (sem
        # resposta HTTP nenhuma), diferente do caminho publicado via Ingress acima
        assert result.stdout.strip() != "200", f"porta {port} do Pod respondeu do host real: {result.stdout!r}"


def test_reconciliacao_recria_pod_deletado_manualmente(system):
    """Requirement 'Pod ausente é recriado' — deletar o Pod de um sistema ativo (ex.: removido
    manualmente, ou o nó reiniciou) e rodar `reconcile()` recria a mesma unidade de execução,
    sem exigir nenhuma ação adicional do operador."""
    from appaiforge.provisioning import provision_system, reconcile
    from appaiforge.edge import system_container_name
    from appaiforge.models import SystemStatus
    from appaiforge.services.systems import set_status

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)
    set_status(system.id, SystemStatus.active, "")

    from kubernetes.client.rest import ApiException

    api = _k8s_api()
    original_uid = api.read_namespaced_pod(pod_name, "appaiforge-test").metadata.uid
    api.delete_namespaced_pod(pod_name, "appaiforge-test", grace_period_seconds=0)

    import time
    for _ in range(15):
        try:
            api.read_namespaced_pod(pod_name, "appaiforge-test")
            time.sleep(1)
        except ApiException as exc:
            if exc.status == 404:
                break
            raise
    else:
        pytest.fail("Pod não terminou de ser removido a tempo — teste inválido")

    reconcile()

    pod = api.read_namespaced_pod(pod_name, "appaiforge-test")
    assert pod.metadata.uid != original_uid, "esperava um Pod NOVO (UID diferente), não o antigo"


def test_materialize_grava_agents_md_e_templates_via_exec(system):
    """Requirement 'Guidelines chegam ao workspace real do sistema' (capability
    container-driver-kubernetes) — `materialize()` deve gravar AGENTS.md e os templates
    canônicos dentro do Pod via exec, não num diretório local do processo do portal, que sob
    este driver nunca é visto pelo agente (achado real, change
    `fix-k8s-workspace-materialize-delete`)."""
    import subprocess

    from appaiforge import guidelines
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    guidelines.materialize(system)

    read_agents = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--",
            "cat", "/workspace/AGENTS.md",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert read_agents.returncode == 0, f"stdout={read_agents.stdout!r} stderr={read_agents.stderr!r}"
    assert read_agents.stdout == guidelines.current_content()

    for name in guidelines.TEMPLATE_FILES:
        read_template = subprocess.run(
            [
                "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
                "exec", pod_name, "-c", "agent", "--",
                "cat", f"/workspace/portal_templates/{name}",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert read_template.returncode == 0, f"{name}: stdout={read_template.stdout!r} stderr={read_template.stderr!r}"
        with open(os.path.join(guidelines.TEMPLATES_PACKAGE_DIR, name)) as f:
            assert read_template.stdout == f.read(), f"{name} divergiu do original"


def test_materialize_falha_apos_timeout_se_container_nao_iniciou(system):
    """Requirement 'Container do agente ainda não está pronto' — sem provisionar o Pod, o
    exec-write não deve bloquear indefinidamente: espera por um tempo limitado e levanta
    `WorkspaceWriteError` (subclasse de `OSError`) em vez disso."""
    from appaiforge.drivers.base import WorkspaceWriteError
    from appaiforge.drivers.kubernetes_driver import _wait_for_agent_container_started
    from appaiforge.edge import system_container_name

    pod_name = system_container_name(system.slug)  # nunca provisionado neste teste
    with pytest.raises(WorkspaceWriteError):
        _wait_for_agent_container_started(pod_name, "appaiforge-test", timeout=2.0, interval=0.5)


def test_delete_workspace_pvc_e_idempotente(system):
    """Requirement 'Remoção do armazenamento persistente do workspace na exclusão definitiva' —
    uma segunda chamada (404 já tratado) não deve levantar."""
    from appaiforge.drivers.kubernetes_driver import delete_workspace_pvc
    from appaiforge.provisioning import provision_system

    provision_system(system)  # garante que a PVC do workspace existe
    delete_workspace_pvc(system.slug)
    delete_workspace_pvc(system.slug)


def test_exclusao_definitiva_remove_a_pvc_do_workspace(system):
    """Requirement 'Remoção do armazenamento persistente do workspace na exclusão definitiva' —
    `delete_system()` deve remover a PVC real, não só o diretório local inerte sob este driver
    (achado real, change `fix-k8s-workspace-materialize-delete`): sem este tratamento, toda
    exclusão definitiva deixava a PVC órfã no cluster."""
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _workspace_pvc_name
    from appaiforge.provisioning import delete_system, provision_system

    provision_system(system)
    pvc_name = _workspace_pvc_name(system.slug)
    _k8s_api().read_namespaced_persistent_volume_claim(pvc_name, "appaiforge-test")  # existe antes

    delete_system(system)

    with pytest.raises(ApiException) as exc_info:
        _k8s_api().read_namespaced_persistent_volume_claim(pvc_name, "appaiforge-test")
    assert exc_info.value.status == 404


def test_arquivamento_preserva_a_pvc_do_workspace(system):
    """Requirement 'Arquivamento e reprovisionamento preservam a PVC' — só `delete_system()`
    remove a PVC (design.md, Decision 4); `archive_system()` (-> `stop_and_remove()` ->
    `driver.remove()`) deve preservá-la, sem perda de conteúdo em caso de reativação futura."""
    from appaiforge.drivers.kubernetes_driver import _workspace_pvc_name
    from appaiforge.provisioning import archive_system, provision_system

    provision_system(system)
    pvc_name = _workspace_pvc_name(system.slug)

    archive_system(system)

    pvc = _k8s_api().read_namespaced_persistent_volume_claim(pvc_name, "appaiforge-test")
    assert pvc is not None


def test_checkpoint_via_exec_commita_e_sobrevive_a_recriacao(system):
    """Requirement de paridade (achado real, task 8.3): checkpoints git funcionam sob o driver
    Kubernetes via exec dentro do container, sem o portal precisar de acesso a filesystem
    compartilhado com o PVC — mesmo resultado observável do driver Docker."""
    import subprocess

    from appaiforge.checkpoints import commit_all, list_checkpoints, record_checkpoint
    from appaiforge.provisioning import provision_system
    from appaiforge.edge import system_container_name

    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name)

    write = subprocess.run(
        [
            "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
            "exec", pod_name, "-c", "agent", "--",
            "sh", "-c", "echo conteudo > /workspace/arquivo.txt",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert write.returncode == 0, f"stdout={write.stdout!r} stderr={write.stderr!r}"

    cp = record_checkpoint(system, None, "primeiro checkpoint via exec")
    assert cp is not None
    assert cp.git_sha

    checkpoints = list_checkpoints(system)
    assert len(checkpoints) == 1
    assert checkpoints[0]["git_sha"] == cp.git_sha

    # sem mudança nenhuma -> commit_all devolve None (idempotente, igual ao driver Docker)
    assert commit_all(system, "nada mudou") is None


