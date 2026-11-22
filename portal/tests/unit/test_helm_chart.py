"""Chart Helm do portal para produção (change add-production-portal-install, tarefas 4.1 a 4.3).
Renderiza com `helm template`; pula se o helm não estiver instalado."""

import os
import shutil
import subprocess

import pytest
import yaml

CHART = os.path.join(os.path.dirname(__file__), "..", "..", "..", "deploy", "helm", "appaiforge-portal")
PROD_VALUES = os.path.join(CHART, "values-production.yaml")

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm não instalado")


def _render(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "aidb", CHART, "-n", "aidb", *args],
                          capture_output=True, text=True, timeout=60)


def _docs(*args: str) -> list[dict]:
    result = _render(*args)
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _portal_env(docs: list[dict]) -> dict[str, str]:
    deployment = next(d for d in docs if d["kind"] == "Deployment"
                      and d["metadata"]["labels"].get("app.kubernetes.io/component") == "portal")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value") for e in container["env"]}


def test_padrao_e_desenvolvimento_sem_variaveis_novas_nem_rota():
    docs = _docs()
    env = _portal_env(docs)
    assert "APPAIFORGE_INSTALLATION_ROLE" not in env  # padrão do portal: development
    assert not [k for k in env if k.startswith("APPAIFORGE_DEPLOY_") or k == "APPAIFORGE_WEBHOOK_BASE_URL"]
    assert not [d for d in docs if d["kind"] == "IngressRoute"]
    # nome completo: o forwardAuth das apps é chamado pelo Traefik, de outro namespace
    assert env["APPAIFORGE_PORTAL_INTERNAL_URL"] == "http://appaiforge-portal.aidb.svc.cluster.local:8080"


def test_valores_de_producao_chegam_ao_portal():
    env = _portal_env(_docs("-f", PROD_VALUES, "--set", "portal.deploy.pollInterval=15"))
    assert env["APPAIFORGE_INSTALLATION_ROLE"] == "production"
    assert env["APPAIFORGE_WEBHOOK_BASE_URL"] == "https://aidb-prod.exemplo.com"
    assert env["APPAIFORGE_DEPLOY_POLL_INTERVAL"] == "15"
    assert env["APPAIFORGE_DEPLOY_HEALTH_TIMEOUT"] == "90"
    assert env["APPAIFORGE_DEPLOY_HEALTH_INTERVAL"] == "2"
    assert env["APPAIFORGE_SEED_DEMO_ADMIN"] == "0"
    assert env["APPAIFORGE_K8S_NAMESPACE"] == "aidb"  # o da release, coberto pela RBAC


def test_producao_com_admin_de_demonstracao_e_recusada():
    result = _render("-f", PROD_VALUES, "--set", "portal.seedDemoAdmin=true")
    assert result.returncode != 0 and "admin de demonstração" in result.stderr


def test_producao_sem_secret_externo_e_recusada():
    result = _render("-f", PROD_VALUES, "--set", "secrets.existingSecret=")
    assert result.returncode != 0 and "secrets.existingSecret" in result.stderr


def test_papel_invalido_e_recusado():
    result = _render("--set", "portal.installationRole=prod")
    assert result.returncode != 0 and "development ou production" in result.stderr


ROUTE_ON = ("--set", "portalRoute.enabled=true", "--set", "portalRoute.host=aidb.exemplo.com")
GATEWAY = ("--set", "routing.mode=gateway")


def _kind(docs: list[dict], kind: str) -> list[dict]:
    return [d for d in docs if d["kind"] == kind]


def test_rota_do_portal_ligada():
    docs = _docs(*ROUTE_ON)
    route = next(d for d in docs if d["kind"] == "IngressRoute")
    rule = route["spec"]["routes"][0]
    assert rule["match"] == "Host(`aidb.exemplo.com`) && PathPrefix(`/`)"
    assert rule["priority"] == 1
    assert rule["services"][0]["port"] == 8080
    assert route["spec"]["entryPoints"] == ["web"]
    assert "tls" not in route["spec"]
    assert not _kind(docs, "HTTPRoute")


def test_rota_do_portal_com_tls():
    docs = _docs(*ROUTE_ON, "--set", "portalRoute.tlsSecretName=aidb-tls")
    route = next(d for d in docs if d["kind"] == "IngressRoute")
    assert route["spec"]["tls"] == {"secretName": "aidb-tls"}


@pytest.mark.parametrize("mode", ["ingressroute", "gateway"])
def test_rota_ligada_sem_host_falha(mode):
    result = _render("--set", "portalRoute.enabled=true", "--set", f"routing.mode={mode}")
    assert result.returncode != 0 and "portalRoute.host" in result.stderr


@pytest.mark.parametrize("mode", ["ingressroute", "gateway"])
def test_rota_do_portal_desligada_por_padrao(mode):
    docs = _docs("--set", f"routing.mode={mode}")
    assert not _kind(docs, "IngressRoute") and not _kind(docs, "HTTPRoute")


def test_rota_do_portal_no_modo_gateway():
    docs = _docs(*ROUTE_ON, *GATEWAY)
    assert not _kind(docs, "IngressRoute")
    route = _kind(docs, "HTTPRoute")[0]
    assert route["spec"]["hostnames"] == ["aidb.exemplo.com"]
    assert route["spec"]["parentRefs"] == [{"name": "appaiforge-portal", "namespace": "aidb"}]
    rule = route["spec"]["rules"][0]
    assert rule["matches"] == [{"path": {"type": "PathPrefix", "value": "/"}}]
    assert rule["backendRefs"] == [{"name": "appaiforge-portal", "port": 8080}]
    # o portal recebe o host para as rotas dos sistemas (D2)
    assert _portal_env(docs)["APPAIFORGE_K8S_ROUTE_HOSTNAME"] == "aidb.exemplo.com"


def test_rota_do_portal_no_modo_gateway_com_tls_fica_no_listener():
    docs = _docs(*ROUTE_ON, *GATEWAY, "--set", "portalRoute.tlsSecretName=aidb-tls")
    gateway = _kind(docs, "Gateway")[0]
    https = next(listener for listener in gateway["spec"]["listeners"] if listener["protocol"] == "HTTPS")
    assert https["hostname"] == "aidb.exemplo.com"
    assert https["port"] == 8443
    assert https["tls"] == {"mode": "Terminate", "certificateRefs": [{"kind": "Secret", "name": "aidb-tls"}]}
    assert "tls" not in _kind(docs, "HTTPRoute")[0]["spec"]


def _traefik_deployment(docs: list[dict]) -> list[dict]:
    return [d for d in docs if d["kind"] == "Deployment"
            and d["metadata"]["labels"].get("app.kubernetes.io/name") == "traefik"]


def test_padrao_instala_traefik_sem_gateway():
    docs = _docs()
    assert _traefik_deployment(docs)
    assert [g["metadata"]["name"] for g in _kind(docs, "GatewayClass")] == ["traefik"]
    assert not _kind(docs, "Gateway")
    env = _portal_env(docs)
    assert env["APPAIFORGE_K8S_ROUTING_MODE"] == "ingressroute"
    assert not [k for k in env if k.startswith("APPAIFORGE_K8S_GATEWAY_") or k == "APPAIFORGE_K8S_ROUTE_HOSTNAME"]


def test_traefik_com_os_dois_providers():
    traefik = _traefik_deployment(_docs())[0]
    args = traefik["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--providers.kubernetescrd" in args
    assert "--providers.kubernetesgateway" in args
    assert not [a for a in args if a.startswith("--providers.kubernetesingress")]


def test_modo_invalido_e_recusado():
    result = _render("--set", "routing.mode=ingress")
    assert result.returncode != 0 and "ingressroute ou gateway" in result.stderr


def test_modo_gateway_cria_gateway_e_aceita_o_namespace_dos_sistemas():
    docs = _docs(*GATEWAY, "--set", "portal.systemsNamespace=aidb-sistemas")
    gateway = _kind(docs, "Gateway")[0]
    assert gateway["metadata"] == {**gateway["metadata"], "name": "appaiforge-portal", "namespace": "aidb"}
    assert gateway["spec"]["gatewayClassName"] == "traefik"
    (web,) = gateway["spec"]["listeners"]  # sem TLS, só HTTP
    assert (web["name"], web["port"], web["protocol"]) == ("web", 8000, "HTTP")
    expr = web["allowedRoutes"]["namespaces"]["selector"]["matchExpressions"][0]
    assert expr["key"] == "kubernetes.io/metadata.name" and expr["values"] == ["aidb", "aidb-sistemas"]
    env = _portal_env(docs)
    assert env["APPAIFORGE_K8S_ROUTING_MODE"] == "gateway"
    assert env["APPAIFORGE_K8S_GATEWAY_NAME"] == "appaiforge-portal"
    assert env["APPAIFORGE_K8S_GATEWAY_NAMESPACE"] == "aidb"
    assert "APPAIFORGE_K8S_ROUTE_HOSTNAME" not in env  # sem rota do portal, sem hostname


def test_modo_gateway_sem_traefik_nem_gateway_existente_e_recusado():
    result = _render(*GATEWAY, "--set", "traefik.enabled=false")
    assert result.returncode != 0 and "gateway.existing" in result.stderr


def test_modo_gateway_com_gateway_existente():
    docs = _docs(*GATEWAY, *ROUTE_ON, "--set", "traefik.enabled=false",
                 "--set", "gateway.existing.name=entrada", "--set", "gateway.existing.namespace=infra")
    assert not _traefik_deployment(docs) and not _kind(docs, "Gateway") and not _kind(docs, "GatewayClass")
    assert _kind(docs, "HTTPRoute")[0]["spec"]["parentRefs"] == [{"name": "entrada", "namespace": "infra"}]
    env = _portal_env(docs)
    assert (env["APPAIFORGE_K8S_GATEWAY_NAME"], env["APPAIFORGE_K8S_GATEWAY_NAMESPACE"]) == ("entrada", "infra")


def test_modo_ingressroute_sem_traefik_nao_exige_gateway():
    docs = _docs(*ROUTE_ON, "--set", "traefik.enabled=false")
    assert not _traefik_deployment(docs) and not _kind(docs, "Gateway")
    assert _kind(docs, "IngressRoute")


def test_crds_da_gateway_api_vem_com_o_chart():
    result = _render("--include-crds")
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    crds = [d["metadata"]["name"] for d in docs if d["kind"] == "CustomResourceDefinition"]
    assert {"httproutes.gateway.networking.k8s.io", "gateways.gateway.networking.k8s.io",
            "gatewayclasses.gateway.networking.k8s.io"} <= set(crds)
    assert "ingressroutes.traefik.io" in crds  # do subchart
    # a política safe-upgrades do arquivo de release da Gateway API não vem junto (D4)
    assert not [d for d in docs if d["kind"].startswith("ValidatingAdmissionPolicy")]


@pytest.mark.parametrize("mode", ["ingressroute", "gateway"])
def test_valores_de_producao_renderizam_nos_dois_modos(mode):
    docs = _docs("-f", PROD_VALUES, "--set", f"routing.mode={mode}")
    assert _portal_env(docs)["APPAIFORGE_K8S_ROUTING_MODE"] == mode
    assert _kind(docs, "IngressRoute" if mode == "ingressroute" else "HTTPRoute")


def test_migracoes_antes_de_subir_so_quando_ligado():
    def init(docs):
        dep = next(d for d in docs if d["kind"] == "Deployment"
                   and d["metadata"]["labels"].get("app.kubernetes.io/component") == "portal")
        return dep["spec"]["template"]["spec"].get("initContainers")

    assert init(_docs()) is None
    containers = init(_docs("-f", PROD_VALUES))
    assert containers and containers[0]["command"] == ["alembic", "upgrade", "head"]
    assert containers[0]["workingDir"] == "/app/portal"
    names = [e["name"] for e in containers[0]["env"]]
    assert names.index("POSTGRES_PASSWORD") < names.index("APPAIFORGE_DATABASE_URL")


def _rbac(docs: list[dict], kind: str) -> dict:
    return next(d for d in docs if d["kind"] == kind)


def test_rbac_cobre_os_objetos_de_rota_dos_dois_modos():
    rules = {(tuple(r["apiGroups"]), tuple(r["resources"])): set(r["verbs"]) for r in _rbac(_docs(), "Role")["rules"]}
    verbs = {"get", "create", "update", "delete"}
    assert rules[(("traefik.io",), ("middlewares", "ingressroutes"))] == verbs
    assert rules[(("gateway.networking.k8s.io",), ("httproutes",))] == verbs


def test_rbac_no_namespace_da_release_por_padrao():
    docs = _docs()
    assert _rbac(docs, "Role")["metadata"]["namespace"] == "aidb"
    assert _rbac(docs, "RoleBinding")["metadata"]["namespace"] == "aidb"


def test_rbac_no_namespace_de_sistemas_separado():
    docs = _docs("--set", "portal.systemsNamespace=aidb-sistemas")
    role, binding = _rbac(docs, "Role"), _rbac(docs, "RoleBinding")
    # a Role vale só onde é criada: precisa estar onde o driver cria os Pods
    assert role["metadata"]["namespace"] == "aidb-sistemas"
    assert binding["metadata"]["namespace"] == "aidb-sistemas"
    # o ServiceAccount continua no namespace da release
    assert binding["subjects"][0]["namespace"] == "aidb"
    assert _portal_env(docs)["APPAIFORGE_K8S_NAMESPACE"] == "aidb-sistemas"


def test_imagem_base_dos_sistemas_so_quando_definida():
    assert "APPAIFORGE_BASE_IMAGE" not in _portal_env(_docs())
    env = _portal_env(_docs("--set", "portal.baseImage=registro.exemplo.com/appaiforge/base:1.4.2"))
    assert env["APPAIFORGE_BASE_IMAGE"] == "registro.exemplo.com/appaiforge/base:1.4.2"


def test_imagem_do_claude_code_e_secrets_de_pull_so_quando_definidos():
    env = _portal_env(_docs())
    assert "APPAIFORGE_CLAUDE_CODE_IMAGE" not in env and "APPAIFORGE_K8S_IMAGE_PULL_SECRETS" not in env
    env = _portal_env(_docs("--set", "portal.claudeCodeImage=r.example/cc:1",
                            "--set", "portal.systemImagePullSecrets={registro-a,registro-b}"))
    assert env["APPAIFORGE_CLAUDE_CODE_IMAGE"] == "r.example/cc:1"
    assert env["APPAIFORGE_K8S_IMAGE_PULL_SECRETS"] == "registro-a,registro-b"


def test_secrets_de_pull_no_formato_do_kubernetes(tmp_path):
    """O imagePullSecrets do Kubernetes é [{name: ...}]; o chart aceita esse formato e nomes."""
    values = tmp_path / "v.yaml"
    values.write_text("portal:\n  systemImagePullSecrets:\n    - name: registro-a\n    - registro-b\n")
    env = _portal_env(_docs("-f", str(values)))
    assert env["APPAIFORGE_K8S_IMAGE_PULL_SECRETS"] == "registro-a,registro-b"
