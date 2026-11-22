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
    # forwardAuth das rotas de app (change add-oidc-sso) chama o portal pelo DNS do Service
    # do portal implantado no cluster pelo chart; precisa ser uma versão com
    # /internal/edge/auth/{slug}.
    monkeypatch.setenv(
        "APPAIFORGE_PORTAL_INTERNAL_URL",
        os.environ.get("APPAIFORGE_TEST_K8S_PORTAL_URL", "http://appaiforge-portal.appaiforge.svc.cluster.local:8080"),
    )
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
    """Remove Pod/ConfigMap/PVC/Service e os objetos de rota do sistema de teste, se
    existirem — mesmo racional do `remove_system_containers` dos testes Docker, pra não
    acumular objetos órfãos no cluster."""
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _config_map_name, _gitdir_pvc_name, _workspace_pvc_name
    from appaiforge.edge import system_container_name

    api = _k8s_api()
    namespace = "appaiforge-test"
    name = system_container_name(slug)
    for delete, resource_name in (
        (lambda n: api.delete_namespaced_pod(n, namespace, grace_period_seconds=0), name),
        (lambda n: api.delete_namespaced_config_map(n, namespace), _config_map_name(slug)),
        (lambda n: api.delete_namespaced_persistent_volume_claim(n, namespace), _workspace_pvc_name(slug)),
        (lambda n: api.delete_namespaced_persistent_volume_claim(n, namespace), _gitdir_pvc_name(slug)),
        (lambda n: api.delete_namespaced_service(n, namespace), name),
    ):
        try:
            delete(resource_name)
        except ApiException as exc:
            if exc.status != 404:
                raise

    # objetos de rota dos dois modos de roteamento (change gateway-api-traefik-subchart)
    from appaiforge.drivers.kubernetes_driver import _all_route_objects, _delete_custom

    custom = k8s.CustomObjectsApi()
    for group, version, plural, object_name in _all_route_objects(name):
        _delete_custom(custom, namespace, group, version, plural, object_name)


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
    # sem conexão de banco cadastrada, o sidecar dbgate não sobe (mesma regra do driver Docker);
    # `git` é o container auxiliar onde o portal executa git (change isolate-workspace-repository)
    assert names == {"agent", "httpsproxy", "git"}


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

    # Sem sessão, o forwardAuth (change add-oidc-sso) responde 302 para o login do portal —
    # prova que Traefik -> Middleware forwardAuth -> portal está de ponta a ponta; com o
    # portal do cluster numa versão anterior ao forwardAuth, o 404 dele vazaria aqui e o
    # teste falharia (sinal de que o chart precisa ser atualizado antes).
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
        if last_code == "302":
            break
        time.sleep(1)
    assert last_code == "302", f"último código: {last_code!r}"


# --- modos de roteamento (change gateway-api-traefik-subchart) -------------------------------
#
# O modo gateway precisa, no cluster de validação: CRDs da Gateway API, o provider
# `kubernetesGateway` no Traefik e um Gateway que aceite rotas do namespace `appaiforge-test` (o
# do chart do portal no modo gateway, por padrão `appaiforge-portal` em `appaiforge`; outro com
# APPAIFORGE_TEST_K8S_GATEWAY_NAME/_NAMESPACE). Sem eles, os casos do modo gateway são pulados.

_EDGE = "http://localhost:18080"
_TEST_GATEWAY = (
    os.environ.get("APPAIFORGE_TEST_K8S_GATEWAY_NAME", "appaiforge-portal"),
    os.environ.get("APPAIFORGE_TEST_K8S_GATEWAY_NAMESPACE", "appaiforge"),
)


def _gateway_available() -> bool:
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    try:
        k8s.CustomObjectsApi().get_namespaced_custom_object(
            "gateway.networking.k8s.io", "v1", _TEST_GATEWAY[1], "gateways", _TEST_GATEWAY[0])
    except ApiException:
        return False
    return True


def _use_mode(monkeypatch, mode: str, hostname: str = "") -> None:
    if mode == "gateway" and not _gateway_available():
        pytest.skip(f"Gateway {_TEST_GATEWAY[1]}/{_TEST_GATEWAY[0]} indisponível no cluster")
    monkeypatch.setenv("APPAIFORGE_K8S_ROUTING_MODE", mode)
    monkeypatch.setenv("APPAIFORGE_K8S_GATEWAY_NAME", _TEST_GATEWAY[0])
    monkeypatch.setenv("APPAIFORGE_K8S_GATEWAY_NAMESPACE", _TEST_GATEWAY[1])
    monkeypatch.setenv("APPAIFORGE_K8S_ROUTE_HOSTNAME", hostname)
    from appaiforge.config import get_settings

    get_settings.cache_clear()


def _get(path: str, host: str | None = None, *, until=None, attempts: int = 20) -> tuple[str, str]:
    """(código, Location) de um GET pela entrada do cluster, sem seguir redirecionamento. Repete
    até `until(código, location)` — o Traefik observa rotas e Services por informers separados,
    e a rota nova leva alguns segundos para valer."""
    import subprocess
    import time

    code = location = ""
    for _ in range(attempts):
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}"]
        if host:
            cmd += ["-H", f"Host: {host}"]
        out = subprocess.run(cmd + [_EDGE + path], capture_output=True, text=True, timeout=15).stdout
        code, _, location = out.partition(" ")
        if until is None or until(code, location):
            break
        time.sleep(1)
    return code, location


def _route_objects(name: str) -> set[str]:
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _all_route_objects

    found = set()
    for group, version, plural, object_name in _all_route_objects(name):
        try:
            k8s.CustomObjectsApi().get_namespaced_custom_object(group, version, "appaiforge-test", plural, object_name)
            found.add(f"{plural}/{object_name}")
        except ApiException as exc:
            if exc.status != 404:
                raise
    return found


def _is_login_redirect(code: str, location: str) -> bool:
    return code == "302" and "/login" in location


@pytest.mark.parametrize("mode", ["ingressroute", "gateway"])
def test_rota_nos_dois_modos_volta_ao_caminho_original(system, monkeypatch, mode):
    """Requirement 'Autenticação da app preservada nos dois modos de roteamento': sem sessão, o
    forwardAuth manda ao login com o caminho ORIGINAL em `next` — no modo gateway isso prova que
    o `ExtensionRef` do auth roda antes do `URLRewrite`."""
    from urllib.parse import quote

    from appaiforge.edge import publish_app, system_container_name
    from appaiforge.provisioning import provision_system

    _use_mode(monkeypatch, mode)
    provision_system(system)
    _wait_pod_running(system_container_name(system.slug))
    publish_app(system)

    path = f"/apps/{system.slug}/relatorios"
    code, location = _get(path, until=_is_login_redirect)
    assert _is_login_redirect(code, location), (code, location)
    assert f"next={quote(path, safe='')}" in location


@pytest.mark.parametrize("mode", ["ingressroute", "gateway"])
def test_app_e_portal_no_mesmo_host(system, monkeypatch, mode):
    """Requirement 'Rota da app não capturada pela rota do portal': com uma rota "/" de portal no
    mesmo host, `/apps/{slug}` continua indo para a rota da app (302 do forwardAuth), e o resto do
    host vai para a rota do portal. O "portal" aqui é o próprio Service do sistema, sem auth: o
    que importa é qual rota casou, não o que responde atrás dela."""
    from kubernetes import client as k8s

    from appaiforge.config import get_settings
    from appaiforge.edge import publish_app, system_container_name
    from appaiforge.provisioning import provision_system

    host = f"{system.slug}.portal.test"
    _use_mode(monkeypatch, mode, hostname=host)
    provision_system(system)
    name = system_container_name(system.slug)
    _wait_pod_running(name)
    publish_app(system)

    app_port = get_settings().app_port
    portal_route = f"{name}-portal-route"
    if mode == "ingressroute":
        group, version, plural = "traefik.io", "v1alpha1", "ingressroutes"
        body = {"apiVersion": "traefik.io/v1alpha1", "kind": "IngressRoute",
                "metadata": {"name": portal_route},
                "spec": {"entryPoints": ["web"], "routes": [{
                    "match": f"Host(`{host}`) && PathPrefix(`/`)", "kind": "Rule", "priority": 1,
                    "services": [{"name": name, "port": app_port}]}]}}
    else:
        group, version, plural = "gateway.networking.k8s.io", "v1", "httproutes"
        body = {"apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
                "metadata": {"name": portal_route},
                "spec": {"parentRefs": [{"name": _TEST_GATEWAY[0], "namespace": _TEST_GATEWAY[1]}],
                         "hostnames": [host],
                         "rules": [{"matches": [{"path": {"type": "PathPrefix", "value": "/"}}],
                                    "backendRefs": [{"name": name, "port": app_port}]}]}}
    custom = k8s.CustomObjectsApi()
    custom.create_namespaced_custom_object(group, version, "appaiforge-test", plural, body)
    try:
        code, location = _get(f"/apps/{system.slug}/", host, until=_is_login_redirect)
        assert _is_login_redirect(code, location), (code, location)
        # a rota do portal casou: nem 404 (sem rota) nem o 302 do forwardAuth da app
        code, location = _get("/outra/pagina", host, until=lambda c, _: c not in ("404", "302"))
        assert code not in ("404", "302"), (code, location)
    finally:
        custom.delete_namespaced_custom_object(group, version, "appaiforge-test", plural, portal_route)


def test_troca_de_modo_nos_dois_sentidos_sem_recriar_pod(system, monkeypatch):
    """Requirement 'Troca de modo de roteamento sem reprovisionamento': a republicação que o
    boot do portal faz (`republish_routes`) migra a rota para o modo novo e apaga a do outro, nos
    dois sentidos, sem recriar o Pod."""
    from appaiforge.edge import publish_app, system_container_name
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import provision_system, republish_routes
    from appaiforge.services.systems import set_status

    if not _gateway_available():
        pytest.skip(f"Gateway {_TEST_GATEWAY[1]}/{_TEST_GATEWAY[0]} indisponível no cluster")
    name = system_container_name(system.slug)
    _use_mode(monkeypatch, "ingressroute")
    provision_system(system)
    _wait_pod_running(name)
    publish_app(system)
    set_status(system.id, SystemStatus.active, "")  # o boot só republica sistemas ativos
    uid = _k8s_api().read_namespaced_pod(name, "appaiforge-test").metadata.uid
    assert _route_objects(name) == {f"ingressroutes/{name}", f"middlewares/{name}-strip", f"middlewares/{name}-auth"}

    for mode, expected in (
        ("gateway", {f"httproutes/{name}", f"middlewares/{name}-auth"}),
        ("ingressroute", {f"ingressroutes/{name}", f"middlewares/{name}-strip", f"middlewares/{name}-auth"}),
    ):
        _use_mode(monkeypatch, mode)
        assert republish_routes() >= 1
        assert _route_objects(name) == expected, mode
        code, location = _get(f"/apps/{system.slug}/", until=_is_login_redirect)
        assert _is_login_redirect(code, location), (mode, code, location)
        assert _k8s_api().read_namespaced_pod(name, "appaiforge-test").metadata.uid == uid, mode


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




# --- change isolate-workspace-repository (capability workspace-repository) -------------------


def _exec_agent(system, script: str) -> str:
    import subprocess

    from appaiforge.edge import system_container_name

    result = subprocess.run(
        ["kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test", "exec",
         system_container_name(system.slug), "-c", "agent", "--", "sh", "-c", script],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    return result.stdout.strip()


def test_repositorio_montado_so_no_container_git(system):
    """Requirement "Repositório do sistema fora do alcance do agente": o PVC do repositório é
    montado só no container `git`; o `agent` monta o workspace, mas não o repositório."""
    from appaiforge.drivers.kubernetes_driver import _gitdir_pvc_name
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)
    pod = _k8s_api().read_namespaced_pod(system_container_name(system.slug), "appaiforge-test")
    gitdir_volumes = {
        v.name for v in pod.spec.volumes
        if v.persistent_volume_claim and v.persistent_volume_claim.claim_name == _gitdir_pvc_name(system.slug)
    }
    assert gitdir_volumes == {"gitdir"}
    # o token da service account (`kube-api-access-*`) é injetado pelo próprio Kubernetes em todo
    # container; não faz parte do que o driver monta
    mounts = {
        c.name: {m.name: m.mount_path for m in (c.volume_mounts or []) if not m.name.startswith("kube-api-access")}
        for c in pod.spec.containers
    }
    assert mounts["git"] == {"workspace": "/workspace", "gitdir": "/gitdir"}
    assert "gitdir" not in mounts["agent"]
    for name, container_mounts in mounts.items():
        if name != "git":
            assert "gitdir" not in container_mounts, f"{name} não pode montar o repositório"
    git = next(c for c in pod.spec.containers if c.name == "git")
    agent = next(c for c in pod.spec.containers if c.name == "agent")
    assert git.security_context == agent.security_context


def test_historico_legado_migrado_no_kubernetes(system):
    """Design D4 sob o driver Kubernetes: o histórico do `.git` antigo do workspace é trazido como
    dado, e a branch aponta para o último checkpoint registrado, não para a ref adulterada."""
    import time

    from appaiforge import checkpoints
    from appaiforge.db import session_scope
    from appaiforge.edge import system_container_name
    from appaiforge.models import Checkpoint
    from appaiforge.provisioning import provision_system

    provision_system(system)
    _wait_pod_running(system_container_name(system.slug), timeout_s=120)
    git = ("env GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t "
           "GIT_CONFIG_GLOBAL=/dev/null git -c safe.directory=* -C /workspace")
    _exec_agent(system, f"{git} init -q -b main")
    shas = []
    for version in ("v1", "v2"):
        sha = _exec_agent(system, f"echo {version} > /workspace/app.txt && {git} add -A && "
                                  f"{git} commit -q -m {version} && {git} rev-parse HEAD")
        shas.append(sha)
        with session_scope() as s:
            s.add(Checkpoint(system_id=system.id, run_id=None, git_sha=sha, message=version,
                             author_id=system.owner_id, author_email=""))
        time.sleep(0.01)
    _exec_agent(system, f"echo agente > /workspace/app.txt && {git} add -A && {git} commit -q -m plantado "
                        "&& echo v2 > /workspace/app.txt")

    checkpoints.ensure_repo(system)
    assert checkpoints._git(system, "rev-parse", "HEAD") == shas[-1]
    checkpoints.rollback(system, shas[0])
    assert _exec_agent(system, "cat /workspace/app.txt") == "v1"
    # o agente continua dono do que o portal escreveu
    _exec_agent(system, "echo editado >> /workspace/app.txt")


def test_pod_sem_container_git_recusa_e_reconciliacao_recria(system, monkeypatch):
    """Pod criado antes do container `git`: a operação git falha com mensagem clara (nunca cai no
    container `agent`), e a reconciliação recria o pod com o container."""
    from kubernetes import client as k8s

    from appaiforge import checkpoints
    from appaiforge.drivers import kubernetes_driver
    from appaiforge.edge import system_container_name
    from appaiforge.git_backend import GitError
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import provision_system, reconcile
    from appaiforge.services.systems import set_status

    original = kubernetes_driver._git_container
    monkeypatch.setattr(
        kubernetes_driver, "_git_container",
        lambda system, settings: k8s.V1Container(name="antigo", image=settings.base_image, command=["sleep", "infinity"]),
    )
    provision_system(system)
    pod_name = system_container_name(system.slug)
    _wait_pod_running(pod_name, timeout_s=120)
    set_status(system.id, SystemStatus.active, "")
    _exec_agent(system, "echo x > /workspace/app.txt")

    with pytest.raises(GitError, match="não tem o container 'git'"):
        checkpoints.record_checkpoint(system, None, "pod antigo")
    assert _exec_agent(system, "test -e /workspace/.git && echo sim || echo nao") == "nao", \
        "nenhuma operação git pode ter caído no container agent"

    monkeypatch.setattr(kubernetes_driver, "_git_container", original)
    reconcile()
    pod = _k8s_api().read_namespaced_pod(pod_name, "appaiforge-test")
    assert "git" in {c.name for c in pod.spec.containers}
    assert checkpoints.record_checkpoint(system, None, "depois da reconciliação") is not None


def test_exclusao_definitiva_remove_a_pvc_do_repositorio(system):
    from kubernetes.client.rest import ApiException

    from appaiforge.drivers.kubernetes_driver import _gitdir_pvc_name
    from appaiforge.provisioning import delete_system, provision_system

    provision_system(system)
    pvc_name = _gitdir_pvc_name(system.slug)
    _k8s_api().read_namespaced_persistent_volume_claim(pvc_name, "appaiforge-test")
    delete_system(system)
    with pytest.raises(ApiException) as exc_info:
        _k8s_api().read_namespaced_persistent_volume_claim(pvc_name, "appaiforge-test")
    assert exc_info.value.status == 404


def test_arquivamento_preserva_a_pvc_do_repositorio(system):
    from appaiforge.drivers.kubernetes_driver import _gitdir_pvc_name
    from appaiforge.provisioning import archive_system, provision_system

    provision_system(system)
    archive_system(system)
    assert _k8s_api().read_namespaced_persistent_volume_claim(_gitdir_pvc_name(system.slug), "appaiforge-test")


def test_sistema_so_implantacao_sobe_sem_agente_no_kubernetes(k8s_env, clean_db):
    """change add-deploy-only-system, tarefa 2.2: o container `agent` do Pod de um sistema só
    implantação roda só a app — sem processo de agente nem variável de LLM."""
    import subprocess
    import time

    from appaiforge import auth
    from appaiforge.edge import system_container_name
    from appaiforge.models import UserType
    from appaiforge.provisioning import provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system

    catalog.ensure_presets()
    editor = auth.create_user("k8s-deploy@t.local", "pw", UserType.editor.value)
    sys = create_system(editor, "Prod K8s", f"k8sdep-{os.urandom(3).hex()}", kind=KIND_DEPLOY_ONLY)
    try:
        provision_system(sys)
        pod_name = system_container_name(sys.slug)
        _wait_pod_running(pod_name, timeout_s=60)
        time.sleep(3)

        def run(cmd):
            return subprocess.run(
                ["kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
                 "exec", pod_name, "-c", "agent", "--", *cmd],
                capture_output=True, text=True, timeout=30,
            ).stdout

        env_lines = run(["env"]).splitlines()
        cmdlines = run(["sh", "-c", "for f in /proc/[0-9]*/cmdline; do tr '\\0' ' ' < $f; echo; done"])
        names = [line.split("=", 1)[0] for line in env_lines if "=" in line]
        assert "AIDB_SYSTEM_KIND=deploy_only" in env_lines
        assert not [n for n in names if any(m in n for m in ("API_KEY", "AIDB_AGENT_PROFILE", "INFERENCE", "BROKER"))], names
        assert "opencode" not in cmdlines and "claude" not in cmdlines, cmdlines
    finally:
        _cleanup(sys.slug)


def test_exec_in_app_no_kubernetes_roda_no_container_da_app(system):
    from appaiforge.drivers import get_driver
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)
    _wait_pod_running(system_container_name(system.slug), timeout_s=60)
    code, out, _ = get_driver().exec_in_app(system, ["sh", "-c", "id -u; echo $HTTPS_PROXY; echo $EXTRA"], env={"EXTRA": "ok"})
    uid, proxy, extra = out.split()
    assert code == 0 and uid == "1000" and proxy.startswith("http://127.0.0.1:") and extra == "ok"
    code, _, err = get_driver().exec_in_app(system, ["sh", "-c", "echo falhou >&2; exit 3"])
    assert code == 3 and "falhou" in err
