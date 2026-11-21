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


def test_rota_do_portal_ligada():
    docs = _docs("--set", "portalRoute.enabled=true", "--set", "portalRoute.host=aidb.exemplo.com")
    route = next(d for d in docs if d["kind"] == "IngressRoute")
    rule = route["spec"]["routes"][0]
    assert rule["match"] == "Host(`aidb.exemplo.com`) && PathPrefix(`/`)"
    assert rule["priority"] == 1
    assert rule["services"][0]["port"] == 8080
    assert route["spec"]["entryPoints"] == ["web"]
    assert "tls" not in route["spec"]


def test_rota_do_portal_com_tls():
    docs = _docs("--set", "portalRoute.enabled=true", "--set", "portalRoute.host=aidb.exemplo.com",
                 "--set", "portalRoute.tlsSecretName=aidb-tls")
    route = next(d for d in docs if d["kind"] == "IngressRoute")
    assert route["spec"]["tls"] == {"secretName": "aidb-tls"}


def test_rota_ligada_sem_host_falha():
    result = _render("--set", "portalRoute.enabled=true")
    assert result.returncode != 0 and "portalRoute.host" in result.stderr


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
