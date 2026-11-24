"""E2E com GitLab local e dois portais: sistema só implantação (change add-deploy-only-system,
tarefas 1.4, 2.4, 4.5 e 7.2).

Homologação (8083) envia e promove; o pipeline da main cria a tag; produção (8084) cria o sistema
a partir do repositório com chave só leitura, confere o manifesto, implanta a tag e serve a app;
uma tag nova chega sozinha por webhook; voltar a uma versão anterior permanece."""

import json
import subprocess
import time
import urllib.request
import uuid

import pytest

import gitlab
from conftest import PORTAL_CONTAINER, PROD_BASE_URL, PROD_PORTAL_CONTAINER, portal_python
from test_repository_link import _create_user, _login, _send, _wait_badge
from test_repository_sync import _agent_write, _linked_system

pytestmark = pytest.mark.e2e

PYPROJECT = '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = []\n'
LOCK = ('version = 1\nrequires-python = ">=3.9"\n\n[[package]]\nname = "app"\nversion = "0.1.0"\n'
        'source = { virtual = "." }\n')

# Conexão do catálogo já autorizada e ativa com o alias "vendas" (change add-db-manager-role): é o
# alias que o manifesto grava e o deploy confere.
_ADD_CONNECTION = """
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, DbConnectionGrant, System
from sqlalchemy import select
with session_scope() as s:
    sid = s.execute(select(System.id).where(System.slug == {slug!r})).scalar_one()
    conn = DbConnection(name="vendas ({slug})", kind="postgres", host="db-{where}", port=5432,
                        database="vendas", username="app", password_encrypted="x")
    s.add(conn)
    s.flush()
    s.add(DbConnectionGrant(connection_id=conn.id, system_id=sid, max_mode="read_write", mode="read_write",
                            active=True, alias="vendas", alias_key="VENDAS"))
"""

_CURRENT = """
import json
from appaiforge import deploy
from appaiforge.services.systems import get_system_by_slug
cur = deploy.current_deployment(get_system_by_slug({slug!r}).id)
print(json.dumps(cur))
"""


def _expect_notification(page, expected: str, timeout_ms: int = 120_000) -> str:
    deadline = time.time() + timeout_ms / 1000
    seen: list[str] = []
    while time.time() < deadline:
        texts = page.locator(".q-notification").all_inner_texts()
        seen.extend(t for t in texts if t not in seen)
        for text in texts:
            if expected in text:
                return text
        page.wait_for_timeout(300)
    raise AssertionError(f"notificação {expected!r} não apareceu; apareceram: {seen}")


def _current(slug: str) -> dict | None:
    return json.loads(portal_python(_CURRENT.format(slug=slug), PROD_PORTAL_CONTAINER).strip().splitlines()[-1])


def _wait_current(slug: str, tag: str, timeout_s: int = 240) -> dict:
    deadline = time.time() + timeout_s
    current = None
    while time.time() < deadline:
        current = _current(slug)
        if current and current["tag"] == tag:
            return current
        time.sleep(3)
    raise AssertionError(f"versão atual esperada {tag}, ficou {current}")


def _app_text(page, slug: str) -> str:
    page.goto(f"/apps/{slug}/")
    return page.locator("body").inner_text().strip()


def _wait_app(page, slug: str, marker: str, timeout_s: int = 90) -> None:
    """A app de produção responde em /apps/{slug} e o workspace tem a versão esperada. O harness
    fake de homologação sempre gera a mesma app; o que distingue as versões é o `notas.txt` que o
    pedido "anote ..." grava em cada uma."""
    deadline = time.time() + timeout_s
    text = notes = ""
    while time.time() < deadline:
        text = _app_text(page, slug)
        notes = subprocess.run(["docker", "exec", f"appaiforge-sys-{slug}", "cat", "/workspace/notas.txt"],
                               capture_output=True, text=True).stdout.strip()
        if f"App de exemplo do sistema {slug}" in text and notes == marker:
            return
        time.sleep(2)
    raise AssertionError(f"produção respondeu {text!r} com notas {notes!r}, esperado {marker!r}")


def _promote(page, pid: int) -> str:
    """Homologação: token de projeto, solicitação de promoção pela aba, merge do humano com
    pipeline verde; devolve a tag que o pipeline da main criou."""
    page.locator('[data-testid=tab-repository]').click()
    _wait_badge(page, "sincronizado")
    page.locator('[data-testid=repo-token]').fill(gitlab.project_token(pid))
    page.locator('[data-testid=repo-token-save]').click()
    _expect_notification(page, "Token cadastrado")
    page.locator('[data-testid=repo-promote]').click()
    _expect_notification(page, "Merge request aberto")
    mr = gitlab.open_mrs(pid)[0]
    assert gitlab.merge_when_green(pid, mr["iid"])["state"] == "merged"
    return gitlab.wait_tag(pid, gitlab.branch(pid, "main")["commit"]["id"])["name"]


def _homolog_release(page, slug: str, pid: int, marker: str) -> str:
    _agent_write(slug, "app/pyproject.toml", PYPROJECT)
    _agent_write(slug, "app/uv.lock", LOCK)
    _send(page, f"anote {marker}")
    local = subprocess.run(["docker", "exec", PORTAL_CONTAINER, "git", "--git-dir", f"/gitdirs/{slug}",
                            "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
    gitlab.wait_branch(pid, "homolog", sha=local)
    return _promote(page, pid)


def _wait_deploy_tab(page, timeout_s: int = 120) -> None:
    page.locator('[data-testid=tab-deploy]').wait_for(timeout=timeout_s * 1000)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if "ativo" in page.locator(".q-badge").all_inner_texts():
            return
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento do sistema só implantação não concluiu")


def _create_prod_system(page, slug: str) -> None:
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-kind-fixed]').wait_for(timeout=15_000)
    assert page.locator('[data-testid=system-kind]').count() == 0
    assert not page.locator('[data-testid=system-provider]').is_visible()
    page.locator('[data-testid=system-name]').fill("Loja em produção")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_deploy_tab(page)
    assert page.get_by_role("tab", name="Chat").count() == 0
    assert page.get_by_role("tab", name="Checkpoints").count() == 0
    assert page.locator('[data-testid=system-kind-badge]').is_visible()


def _link_prod_repository(page, pid: int, project: dict) -> None:
    key = page.locator('[data-testid=deploy-public-key]').input_value()
    gitlab.add_deploy_key(pid, key, can_push=False)
    page.locator('[data-testid=deploy-url]').fill(gitlab.ssh_url(project))
    page.locator('[data-testid=deploy-save]').click()
    _expect_notification(page, "Repositório salvo")
    page.locator('[data-testid=deploy-test-connection]').click()
    page.locator('[data-testid=deploy-confirm-host]').click()
    _expect_notification(page, "Conexão válida")


def _click_deploy(page, tag: str) -> str:
    """Clica "Implantar" na linha da tag e devolve a notificação de resultado desta implantação
    (não uma que já estava na tela)."""
    page.locator('[data-testid=deploy-refresh]').click()
    page.wait_for_timeout(3000)  # a lista é refeita pelo "Atualizar": clicar antes perde o clique
    button = page.locator(f'[data-testid="deploy-run-{tag}"]')
    button.wait_for(timeout=30_000)
    before = page.locator(".q-notification").all_inner_texts()
    button.click()
    deadline = time.time() + 180
    while time.time() < deadline:
        fresh = page.locator(".q-notification").all_inner_texts()
        for old in before:  # o que já estava na tela não conta, em qualquer ordem
            if old in fresh:
                fresh.remove(old)
        for text in fresh:
            if f"{tag} implantada" in text or f"{tag} não foi implantada" in text:
                return text
        page.wait_for_timeout(500)
    raise AssertionError(f"implantação de {tag} não terminou")


def _deployed(text: str, tag: str) -> bool:
    return f"{tag} implantada" in text and "não foi" not in text


def _remote_refs(pid: int) -> list[tuple[str, str]]:
    branches = [(b["name"], b["commit"]["id"]) for b in gitlab.api("GET", f"/projects/{pid}/repository/branches")]
    tags = [(t["name"], t["commit"]["id"]) for t in gitlab.api("GET", f"/projects/{pid}/repository/tags")]
    return sorted(branches + tags)


def test_criacao_em_desenvolvimento_oferece_o_tipo(page):
    """1.4/2.4 no portal de desenvolvimento (homologação): escolher "só implantação" esconde o
    provedor; a página do sistema não tem Chat nem Checkpoints e tem a aba Implantação."""
    suffix = uuid.uuid4().hex[:8]
    editor = f"tipo-{suffix}@e2e.local"
    _create_user(page, editor, "editor")
    _login(page, editor, "pw-e2e")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-provider]').wait_for(timeout=15_000)
    page.locator('[data-testid=system-kind]').get_by_text("Só implantação").click()
    page.locator('[data-testid=system-provider]').wait_for(state="hidden", timeout=5_000)
    page.locator('[data-testid=system-name]').fill("Só implantação em desenvolvimento")
    page.locator('[data-testid=system-slug]').fill(f"dev-dep-{suffix}")
    page.locator('[data-testid=create-system]').click()
    _wait_deploy_tab(page)
    assert page.get_by_role("tab", name="Chat").count() == 0
    assert page.get_by_role("tab", name="Checkpoints").count() == 0
    page.get_by_role("tab", name="Configurações").click()
    assert page.locator('[data-testid=edit-provider]').count() == 0, "sem provedor de LLM para editar"
    assert page.get_by_text("Com agente").count() == 0, "o tipo não é editável"
    page.get_by_text("Rede de saída da app").wait_for(timeout=5_000)
    assert page.get_by_text("broker de inferência").count() == 0, "não há broker neste container"
    assert page.locator('[data-testid=toggle-internet-enabled]').count() == 1
    assert page.locator('[data-testid=toggle-restricted-network]').count() == 1


def test_jornada_homologacao_para_producao(page, browser):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    pid = project["id"]
    prod_slug = f"prod-{suffix}"
    prod_ctx = browser.new_context(base_url=PROD_BASE_URL)
    prod = prod_ctx.new_page()
    try:
        # homologação: a app usa a conexão "vendas"; o manifesto vai junto do checkpoint
        portal_python(_ADD_CONNECTION.format(slug=slug, where="homolog"))
        v1 = _homolog_release(page, slug, pid, "LOJA-V1")
        manifest = gitlab.api("GET", f"/projects/{pid}/repository/files/{gitlab.q('.aidb/manifest.json')}/raw?ref={v1}")
        assert manifest == {"version": 1, "connections": [{"name": "vendas", "kind": "postgres"}]}

        # produção: criação com tipo fixo, chave só leitura, servidor confirmado
        prod_editor = f"prod-editor-{suffix}@e2e.local"
        _create_user(prod, prod_editor, "editor")
        _login(prod, prod_editor, "pw-e2e")
        _create_prod_system(prod, prod_slug)
        _link_prod_repository(prod, pid, project)
        refs_before = _remote_refs(pid)  # entre aqui e o fim das duas implantações só a produção age

        # conexão do manifesto ainda não cadastrada: recusa listando a que falta
        refused = _click_deploy(prod, v1)
        assert "não foi implantada" in refused and "vendas" in refused
        portal_python(_ADD_CONNECTION.format(slug=prod_slug, where="producao"), PROD_PORTAL_CONTAINER)
        assert _deployed(_click_deploy(prod, v1), v1)
        assert _current(prod_slug)["tag"] == v1
        assert v1 in prod.locator('[data-testid=deploy-current]').inner_text()
        assert _remote_refs(pid) == refs_before, "a produção não escreve no repositório"
        _wait_app(prod, prod_slug, "LOJA-V1")
        prod.goto(f"/systems/{_current_system_id(prod_slug)}")
        _wait_deploy_tab(prod)

        # automático por webhook: cadastra o webhook no GitLab com o endereço e o segredo da aba
        prod.locator('[data-testid=deploy-auto]').click()
        prod.locator('[data-testid=deploy-detection]').click()
        prod.locator('.q-menu:visible').get_by_text("Webhook do GitLab", exact=True).click()
        prod.locator('[data-testid=deploy-auto-save]').click()
        _expect_notification(prod, "Implantação automática salva")
        hook_url = prod.locator('[data-testid=deploy-webhook-url]').input_value()
        secret = prod.locator('[data-testid=deploy-webhook-secret]').input_value()
        assert hook_url.endswith(f"/hooks/gitlab/{_current_system_id(prod_slug)}")
        gitlab.api("POST", f"/projects/{pid}/hooks", {
            "url": hook_url, "token": secret, "tag_push_events": True, "push_events": False,
            "enable_ssl_verification": False,
        })

        # nova versão pela homologação: a tag nova chega sozinha à produção
        v2 = _homolog_release(page, slug, pid, "LOJA-V2")
        assert v2 != v1
        current = _wait_current(prod_slug, v2)
        assert current["trigger"] == "webhook" and current["actor_id"] is None
        _wait_app(prod, prod_slug, "LOJA-V2")

        # rollback manual para a anterior permanece, mesmo com outra chamada do webhook
        prod.goto(f"/systems/{_current_system_id(prod_slug)}")
        _wait_deploy_tab(prod)
        assert _deployed(_click_deploy(prod, v1), v1)
        _wait_app(prod, prod_slug, "LOJA-V1")
        req = urllib.request.Request(f"{PROD_BASE_URL}/hooks/gitlab/{_current_system_id(prod_slug)}", data=b"{}",
                                     method="POST", headers={"X-Gitlab-Token": secret})
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 202
        time.sleep(15)
        assert _current(prod_slug)["tag"] == v1
        _wait_app(prod, prod_slug, "LOJA-V1")

        # histórico: tentativa recusada, implantações manual e por webhook, e o rollback
        prod.goto(f"/systems/{_current_system_id(prod_slug)}")
        _wait_deploy_tab(prod)
        history = prod.locator('[data-testid=deploy-history]').inner_text()
        assert v1 in history and v2 in history and "webhook" in history and "falha" in history
        prod.get_by_role("tab", name="Auditoria").click()
        prod.get_by_text("deploy.run").first.wait_for(timeout=30_000)
    finally:
        prod_ctx.close()
        gitlab.delete_project(pid)


_SYSTEM_ID = """
from appaiforge.services.systems import get_system_by_slug
print(get_system_by_slug({slug!r}).id)
"""


def _current_system_id(slug: str) -> str:
    return portal_python(_SYSTEM_ID.format(slug=slug), PROD_PORTAL_CONTAINER).strip().splitlines()[-1]
