"""Piloto: homologação (stack E2E com GitLab, driver Docker) → tag → produção num cluster kind só
dela (aidb-prod), instalada pelo chart com values-production.yaml. Montagem em
deploy/pilot-k8s/README.md; roda só com AIDB_PILOT_K8S=1.

Mesma jornada de test_deploy_only.test_jornada_homologacao_para_producao, com a produção no
Kubernetes: entra com o admin de emergência (produção não tem admin de demonstração) e lê o estado
do portal e do sistema por `kubectl exec`."""

import json
import os
import pathlib
import subprocess
import time
import urllib.request
import uuid

import pytest

import gitlab
from conftest import portal_python
from test_deploy_only import (
    _ADD_CONNECTION,
    _CURRENT,
    _SYSTEM_ID,
    _click_deploy,
    _create_prod_system,
    _deployed,
    _expect_notification,
    _homolog_release,
    _link_prod_repository,
    _remote_refs,
    _wait_deploy_tab,
)
from test_repository_link import _create_user, _login, _logout
from test_repository_sync import _linked_system

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("AIDB_PILOT_K8S") != "1", reason="piloto: AIDB_PILOT_K8S=1"),
]

CONTEXT = os.environ.get("AIDB_PILOT_CONTEXT", "kind-aidb-prod")
NAMESPACE = os.environ.get("AIDB_PILOT_NAMESPACE", "aidb-prod")
DEPLOYMENT = os.environ.get("AIDB_PILOT_DEPLOYMENT", "aidb-prod-portal")
HOST = os.environ.get("AIDB_PILOT_HOST", "aidb-prod.pilot.test")
PORT = os.environ.get("AIDB_PILOT_PORT", "28080")
PROD_URL = f"http://{HOST}:{PORT}"
PILOT_ENV = pathlib.Path(__file__).parents[3] / "deploy" / "pilot-k8s" / "pilot.env"


def _pilot_env() -> dict[str, str]:
    return dict(line.split("=", 1) for line in PILOT_ENV.read_text().split() if "=" in line)


def _kubectl(*args: str) -> str:
    result = subprocess.run(["kubectl", "--context", CONTEXT, "-n", NAMESPACE, *args],
                            capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def prod_python(code: str) -> str:
    return _kubectl("exec", f"deploy/{DEPLOYMENT}", "-c", "portal", "--",
                    "sh", "-c", 'cd /app/portal && python -c "$1"', "sh", code)


def _current(slug: str) -> dict | None:
    return json.loads(prod_python(_CURRENT.format(slug=slug)).strip().splitlines()[-1])


def _wait_current(slug: str, tag: str, timeout_s: int = 240) -> dict:
    deadline = time.time() + timeout_s
    current = None
    while time.time() < deadline:
        current = _current(slug)
        if current and current["tag"] == tag:
            return current
        time.sleep(3)
    raise AssertionError(f"versão atual esperada {tag}, ficou {current}")


def _system_id(slug: str) -> str:
    return prod_python(_SYSTEM_ID.format(slug=slug)).strip().splitlines()[-1]


def _wait_app(page, slug: str, marker: str, timeout_s: int = 120) -> None:
    """A app responde pela rota do Traefik do cluster e o workspace do Pod tem a versão esperada."""
    deadline = time.time() + timeout_s
    text = notes = ""
    while time.time() < deadline:
        page.goto(f"/apps/{slug}/")
        text = page.locator("body").inner_text().strip()
        try:
            notes = _kubectl("exec", f"appaiforge-sys-{slug}", "-c", "agent", "--",
                             "cat", "/workspace/notas.txt").strip()
        except RuntimeError:
            notes = ""
        if f"App de exemplo do sistema {slug}" in text and notes == marker:
            return
        time.sleep(3)
    raise AssertionError(f"produção respondeu {text!r} com notas {notes!r}, esperado {marker!r}")


def _create_prod_user(page, email: str) -> None:
    env = _pilot_env()
    _login(page, env["PILOT_BREAKGLASS_EMAIL"], env["PILOT_BREAKGLASS_PASSWORD"])
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-e2e")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)
    _logout(page)


def test_piloto_homologacao_para_producao_no_kubernetes(page, browser):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    pid = project["id"]
    prod_slug = f"prod-{suffix}"
    prod_ctx = browser.new_context(base_url=PROD_URL)
    prod = prod_ctx.new_page()
    try:
        portal_python(_ADD_CONNECTION.format(slug=slug, where="homolog"))
        v1 = _homolog_release(page, slug, pid, "PILOTO-V1")

        prod_editor = f"prod-editor-{suffix}@pilot.test"
        _create_prod_user(prod, prod_editor)
        _login(prod, prod_editor, "pw-e2e")
        _create_prod_system(prod, prod_slug)
        _link_prod_repository(prod, pid, project)
        refs_before = _remote_refs(pid)

        refused = _click_deploy(prod, v1)
        assert "não foi implantada" in refused and "vendas" in refused
        prod_python(_ADD_CONNECTION.format(slug=prod_slug, where="producao"))
        assert _deployed(_click_deploy(prod, v1), v1)
        assert _current(prod_slug)["tag"] == v1
        assert _remote_refs(pid) == refs_before, "a produção não escreve no repositório"
        _wait_app(prod, prod_slug, "PILOTO-V1")

        system_id = _system_id(prod_slug)
        prod.goto(f"/systems/{system_id}")
        _wait_deploy_tab(prod)
        prod.locator('[data-testid=deploy-auto]').click()
        prod.locator('[data-testid=deploy-detection]').click()
        prod.locator('.q-menu:visible').get_by_text("Webhook do GitLab", exact=True).click()
        prod.locator('[data-testid=deploy-auto-save]').click()
        _expect_notification(prod, "Implantação automática salva")
        hook_url = prod.locator('[data-testid=deploy-webhook-url]').input_value()
        secret = prod.locator('[data-testid=deploy-webhook-secret]').input_value()
        assert hook_url == f"http://{HOST}/hooks/gitlab/{system_id}"
        gitlab.api("POST", f"/projects/{pid}/hooks", {
            "url": hook_url, "token": secret, "tag_push_events": True, "push_events": False,
            "enable_ssl_verification": False,
        })

        v2 = _homolog_release(page, slug, pid, "PILOTO-V2")
        assert v2 != v1
        current = _wait_current(prod_slug, v2)
        assert current["trigger"] == "webhook"
        _wait_app(prod, prod_slug, "PILOTO-V2")

        prod.goto(f"/systems/{system_id}")
        _wait_deploy_tab(prod)
        assert _deployed(_click_deploy(prod, v1), v1)
        _wait_app(prod, prod_slug, "PILOTO-V1")
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/hooks/gitlab/{system_id}", data=b"{}",
                                     method="POST", headers={"X-Gitlab-Token": secret, "Host": HOST})
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 202
        time.sleep(15)
        assert _current(prod_slug)["tag"] == v1
        _wait_app(prod, prod_slug, "PILOTO-V1")
    finally:
        prod_ctx.close()
        gitlab.delete_project(pid)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # o host do portal de produção não está no DNS: o navegador o resolve para a porta do kind
    return {**browser_type_launch_args, "args": [f"--host-resolver-rules=MAP {HOST} 127.0.0.1"]}
