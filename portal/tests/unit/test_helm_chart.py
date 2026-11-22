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


# --- Observabilidade (change chart-observability-otel) ------------------------------------

OBS = ("--set", "observability.enabled=true", "--set", "observability.exporter.endpoint=apm.exemplo.com:8200")
TRAEFIK_TRACING = ("--set", "traefik.tracing.otlp.enabled=true", "--set", "traefik.tracing.otlp.http.enabled=true")
KUBELETSTATS = ("--set", "observability.kubeletstats.enabled=true")
COLLECTOR_BASE = "http://appaiforge-portal-otel-collector.aidb.svc.cluster.local:4318"


def _named(docs: list[dict], kind: str, suffix: str) -> list[dict]:
    return [d for d in _kind(docs, kind) if d["metadata"]["name"].endswith(suffix)]


def _collector_config(docs: list[dict], suffix: str = "otel-collector") -> dict:
    return yaml.safe_load(_named(docs, "ConfigMap", suffix)[0]["data"]["config.yaml"])


def _pod_spec(docs: list[dict], kind: str, suffix: str) -> dict:
    return _named(docs, kind, suffix)[0]["spec"]["template"]["spec"]


def _portal_env_full(docs: list[dict]) -> list[dict]:
    deployment = next(d for d in docs if d["kind"] == "Deployment"
                      and d["metadata"]["labels"].get("app.kubernetes.io/component") == "portal")
    return deployment["spec"]["template"]["spec"]["containers"][0]["env"]


def test_observabilidade_desligada_nao_cria_collector_nem_variaveis():
    docs = _docs()
    assert not [d for d in docs if "otel" in d["metadata"]["name"]]
    env = _portal_env(docs)
    assert not [k for k in env if k.startswith("APPAIFORGE_OTEL_") or k.startswith("OTEL_")]
    assert "POD_NAME" not in env


@pytest.mark.parametrize("args, message", [
    (("--set", "observability.enabled=true"), "observability.exporter.endpoint"),
    (("--set", "observability.enabled=true", "--set", "observability.collector.create=false"),
     "observability.collector.endpoint"),
    (TRAEFIK_TRACING, "observability.enabled=true"),
    ((*OBS, *TRAEFIK_TRACING, "--set", "fullnameOverride=outro"), "não aponta para o Collector"),
    ((*OBS, "--set", "observability.exporter.authScheme=Basic"), "Bearer ou ApiKey"),
])
def test_observabilidade_mal_configurada_e_recusada(args, message):
    result = _render(*args)
    assert result.returncode != 0 and message in result.stderr, result.stderr


def test_collector_central_com_os_tres_pipelines_e_delta():
    docs = _docs(*OBS)
    config = _collector_config(docs)
    assert config["exporters"]["otlp"]["endpoint"] == "apm.exemplo.com:8200"
    assert config["exporters"]["otlp"]["tls"] == {"insecure": False}
    pipelines = config["service"]["pipelines"]
    assert set(pipelines) == {"traces", "metrics", "logs"}
    assert "cumulativetodelta" in pipelines["metrics"]["processors"]
    assert all(p["exporters"] == ["otlp"] for p in pipelines.values())
    service = _named(docs, "Service", "otel-collector")[0]
    assert {p["port"] for p in service["spec"]["ports"]} == {4317, 4318}


def test_collector_sem_delta_quando_o_destino_quer_cumulativo():
    config = _collector_config(_docs(*OBS, "--set", "observability.exporter.deltaMetrics=false"))
    assert "cumulativetodelta" not in config["processors"]
    assert "cumulativetodelta" not in config["service"]["pipelines"]["metrics"]["processors"]


def test_configuracao_propria_substitui_a_gerada(tmp_path):
    values = tmp_path / "v.yaml"
    values.write_text("observability:\n  enabled: true\n  collector:\n    config: |\n"
                      "      receivers: {otlp: {protocols: {http: {}}}}\n"
                      "      exporters: {debug: {}}\n"
                      "      service: {pipelines: {traces: {receivers: [otlp], exporters: [debug]}}}\n")
    docs = _docs("-f", str(values))
    assert _collector_config(docs) == {
        "receivers": {"otlp": {"protocols": {"http": {}}}}, "exporters": {"debug": {}},
        "service": {"pipelines": {"traces": {"receivers": ["otlp"], "exporters": ["debug"]}}},
    }
    container = _pod_spec(docs, "Deployment", "otel-collector")["containers"][0]
    assert "readinessProbe" not in container  # health_check só existe na configuração gerada


def test_pod_do_collector_endurecido_e_sem_token_do_service_account():
    spec = _pod_spec(_docs(*OBS), "Deployment", "otel-collector")
    assert spec["automountServiceAccountToken"] is False
    context = spec["containers"][0]["securityContext"]
    assert context["readOnlyRootFilesystem"] is True and context["allowPrivilegeEscalation"] is False


def test_credencial_e_ca_so_no_collector():
    docs = _docs(*OBS, "--set", "observability.exporter.existingSecret=apm-destino",
                 "--set", "observability.exporter.authScheme=ApiKey", "--set", "observability.exporter.ca=true")
    config = _collector_config(docs)
    assert config["exporters"]["otlp"]["headers"] == {"Authorization": "${env:EXPORTER_AUTHORIZATION}"}
    assert config["exporters"]["otlp"]["tls"]["ca_file"] == "/etc/otel-exporter/ca.crt"
    container = _pod_spec(docs, "Deployment", "otel-collector")["containers"][0]
    env = {e["name"]: e for e in container["env"]}
    assert env["EXPORTER_TOKEN"]["valueFrom"]["secretKeyRef"] == {"name": "apm-destino", "key": "token"}
    assert env["EXPORTER_AUTHORIZATION"]["value"] == "ApiKey $(EXPORTER_TOKEN)"
    assert [e["name"] for e in container["env"]].index("EXPORTER_TOKEN") < \
        [e["name"] for e in container["env"]].index("EXPORTER_AUTHORIZATION")
    # o Secret do destino só aparece no Collector central
    users = [d["metadata"]["name"] for d in docs if "apm-destino" in yaml.safe_dump(d)]
    assert users == ["appaiforge-portal-otel-collector"]


def test_secret_so_com_ca_nao_monta_cabecalho():
    docs = _docs(*OBS, "--set", "observability.exporter.existingSecret=apm-destino",
                 "--set", "observability.exporter.token=false", "--set", "observability.exporter.ca=true")
    config = _collector_config(docs)
    assert "headers" not in config["exporters"]["otlp"]
    assert "env" not in _pod_spec(docs, "Deployment", "otel-collector")["containers"][0]


def test_sem_secret_nao_ha_cabecalho_nem_ca():
    docs = _docs(*OBS)
    config = _collector_config(docs)
    assert "headers" not in config["exporters"]["otlp"] and "ca_file" not in config["exporters"]["otlp"]["tls"]
    assert len(_pod_spec(docs, "Deployment", "otel-collector")["volumes"]) == 1


def test_portal_recebe_endpoints_e_identificacao():
    docs = _docs(*OBS, "--set", "image.tag=1.9.0", "--set", "observability.environment=producao")
    env = _portal_env(docs)
    assert env["APPAIFORGE_OTEL_TRACES_ENDPOINT"] == f"{COLLECTOR_BASE}/v1/traces"
    assert env["APPAIFORGE_OTEL_METRICS_ENDPOINT"] == f"{COLLECTOR_BASE}/v1/metrics"
    assert env["APPAIFORGE_OTEL_LOGS_ENDPOINT"] == f"{COLLECTOR_BASE}/v1/logs"
    assert env["OTEL_RESOURCE_ATTRIBUTES"] == (
        "service.version=1.9.0,deployment.environment=producao,"
        "k8s.pod.name=$(POD_NAME),k8s.namespace.name=$(POD_NAMESPACE)")
    names = [e["name"] for e in _portal_env_full(docs)]
    assert names.index("POD_NAME") < names.index("OTEL_RESOURCE_ATTRIBUTES")
    assert names.index("POD_NAMESPACE") < names.index("OTEL_RESOURCE_ATTRIBUTES")


def test_portal_sem_ambiente_nao_manda_deployment_environment():
    env = _portal_env(_docs(*OBS))
    assert "deployment.environment" not in env["OTEL_RESOURCE_ATTRIBUTES"]


def test_collector_existente_no_cluster():
    docs = _docs("--set", "observability.enabled=true", "--set", "observability.collector.create=false",
                 "--set", "observability.collector.endpoint=http://otel.observabilidade:4318/")
    assert not [d for d in docs if "otel" in d["metadata"]["name"]]
    assert _portal_env(docs)["APPAIFORGE_OTEL_TRACES_ENDPOINT"] == "http://otel.observabilidade:4318/v1/traces"


def test_tracing_do_traefik_so_quando_ligado():
    args = _traefik_deployment(_docs(*OBS, *TRAEFIK_TRACING))[0]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--tracing.otlp.http.endpoint=http://appaiforge-portal-otel-collector:4318/v1/traces" in args
    default_args = _traefik_deployment(_docs(*OBS))[0]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert not [a for a in default_args if a.startswith("--tracing") or a.startswith("--metrics.otlp")]


def test_kubeletstats_desligado_nao_cria_agente_nem_permissao_de_no():
    docs = _docs(*OBS)
    assert not [d for d in docs if "otel-agent" in d["metadata"]["name"]]
    assert not [d for d in _kind(docs, "ClusterRole") if "nodes/stats" in yaml.safe_dump(d)]


def test_kubeletstats_com_permissoes_minimas():
    docs = _docs(*OBS, *KUBELETSTATS)
    (cluster_role,) = _named(docs, "ClusterRole", "otel-agent")
    assert cluster_role["metadata"]["name"] == "aidb-appaiforge-portal-otel-agent"
    assert cluster_role["rules"] == [{"apiGroups": [""], "resources": ["nodes/stats", "nodes"], "verbs": ["get"]}]
    roles = _named(docs, "Role", "otel-agent")
    assert [r["metadata"]["namespace"] for r in roles] == ["aidb"]
    assert roles[0]["rules"][0]["resources"] == ["pods"]
    spec = _pod_spec(docs, "DaemonSet", "otel-agent")
    assert spec["serviceAccountName"] == "appaiforge-portal-otel-agent"
    assert "--feature-gates=receiver.kubeletstats.enableCPUUsageMetrics" in spec["containers"][0]["args"]
    config = _collector_config(docs, "otel-agent")
    assert config["exporters"]["otlphttp"]["endpoint"] == COLLECTOR_BASE
    assert config["receivers"]["kubeletstats"]["insecure_skip_verify"] is False
    assert "k8sattributes/0" in config["service"]["pipelines"]["metrics"]["processors"]


def test_kubeletstats_com_namespace_de_sistemas_separado():
    docs = _docs(*OBS, *KUBELETSTATS, "--set", "portal.systemsNamespace=aidb-sistemas")
    assert sorted(r["metadata"]["namespace"] for r in _named(docs, "Role", "otel-agent")) == ["aidb", "aidb-sistemas"]
    config = _collector_config(docs, "otel-agent")
    assert config["processors"]["k8sattributes/0"]["filter"]["namespace"] == "aidb"
    assert config["processors"]["k8sattributes/1"]["filter"]["namespace"] == "aidb-sistemas"
    condition = config["processors"]["filter/namespaces"]["metrics"]["metric"][0]
    assert '"aidb"' in condition and '"aidb-sistemas"' in condition


def test_agente_nao_le_o_secret_do_destino():
    docs = _docs(*OBS, *KUBELETSTATS, "--set", "observability.exporter.existingSecret=apm-destino")
    agent = [d for d in docs if "otel-agent" in d["metadata"]["name"]]
    assert agent and not [d for d in agent if "apm-destino" in yaml.safe_dump(d)]
