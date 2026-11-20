"""E2E com GitLab local: aba Repositório e envio dos checkpoints (change add-system-git-remote,
tarefas 4.1-4.3). O teste faz o papel do humano no GitLab pela API."""

import time
import uuid

import pytest

import gitlab
from conftest import portal_python

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"


def _login(page, email: str, password: str) -> None:
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill(email)
    page.locator('[data-testid=login-password]').fill(password)
    page.get_by_role("button", name="Entrar").click()
    page.locator('[data-testid=user-menu]').wait_for(timeout=30_000)


def _logout(page) -> None:
    page.locator('[data-testid=user-menu]').click()
    page.locator('[data-testid=logout]').click()
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def _create_user(page, email: str, kind: str) -> None:
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-e2e")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text(kind, exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)
    _logout(page)


def _wait_active(page, timeout_s: int = 90) -> None:
    page.get_by_role("tab", name="Chat").wait_for(timeout=timeout_s * 1000)
    start = time.time()
    while time.time() - start < timeout_s:
        if "ativo" in page.locator(".q-badge").all_inner_texts():
            return
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def _send(page, prompt: str) -> None:
    page.get_by_role("tab", name="Chat").click()
    page.locator('[data-testid=chat-input]').fill(prompt)
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text(f"Entendi o pedido: {prompt}").wait_for(timeout=30_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)


def _badge_text(page) -> str:
    return page.locator('[data-testid=repo-state]').inner_text().strip().lower()


def _wait_badge(page, expected: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _badge_text(page) == expected:
            return
        page.wait_for_timeout(1000)
    raise AssertionError(f"estado esperado {expected!r}, ficou {_badge_text(page)!r}")


def test_vincula_e_envia_checkpoint_ao_gitlab(page):
    suffix = uuid.uuid4().hex[:8]
    editor = f"repo-editor-{suffix}@e2e.local"
    viewer = f"repo-viewer-{suffix}@e2e.local"
    slug = f"repo-{suffix}"
    _create_user(page, editor, "editor")
    _create_user(page, viewer, "app_user")
    project = gitlab.create_system_project(f"sistema-{suffix}")
    try:
        _login(page, editor, "pw-e2e")
        page.get_by_role("button", name="Novo sistema").click()
        page.locator('[data-testid=system-name]').fill("Sistema Repositório")
        page.locator('[data-testid=system-slug]').fill(slug)
        page.locator('[data-testid=create-system]').click()
        _wait_active(page)

        # 4.1: aba visível para o dono, com a chave pública
        page.locator('[data-testid=tab-repository]').click()
        public_key = page.locator('[data-testid=repo-public-key]').input_value()
        assert public_key.startswith("ssh-ed25519 ")
        assert _badge_text(page) == "desativado"

        # o humano cadastra a chave no GitLab
        gitlab.add_deploy_key(project["id"], public_key)

        page.locator('[data-testid=repo-url]').fill(gitlab.ssh_url(project))
        page.locator('[data-testid=repo-api-url]').fill(gitlab.INTERNAL_API)
        page.locator('[data-testid=repo-save]').click()
        page.get_by_text("Repositório salvo").wait_for(timeout=15_000)

        # teste de conexão: confirma a identidade do servidor no primeiro uso
        page.locator('[data-testid=repo-test]').click()
        page.locator('[data-testid=repo-host-fingerprint]').wait_for(timeout=30_000)
        assert "SHA256:" in page.locator('[data-testid=repo-host-fingerprint]').inner_text()
        page.locator('[data-testid=repo-confirm-host]').click()
        page.get_by_text("Conexão válida").wait_for(timeout=30_000)

        page.locator('[data-testid=repo-enable]').click()
        page.get_by_text("Vínculo ativado").wait_for(timeout=60_000)
        _wait_badge(page, "sincronizado")

        # pedido no chat -> checkpoint -> commit na homolog do GitLab, com o editor como autor
        _send(page, "crie o painel de clientes")
        homolog = gitlab.wait_branch(project["id"], "homolog")
        commit = gitlab.api("GET", f"/projects/{project['id']}/repository/commits/{homolog['commit']['id']}")
        assert commit["author_email"] == editor
        page.locator('[data-testid=tab-repository]').click()
        _wait_badge(page, "sincronizado")
        page.locator('[data-testid=repo-last-sent]').get_by_text(homolog["commit"]["id"][:12]).wait_for(timeout=15_000)
        _logout(page)

        # 4.1: quem tem acesso mas não gerencia o sistema não vê a aba
        portal_python(
            "from appaiforge.services import directory\n"
            f"directory.create_group('e2e-repo-{suffix}')\n"
            f"directory.add_member('e2e-repo-{suffix}', '{viewer}')\n"
            f"directory.link_group_to_system('e2e-repo-{suffix}', '{slug}')\n"
        )
        _login(page, viewer, "pw-e2e")
        page.goto(f"/entry/{slug}")
        page.wait_for_timeout(2000)
        assert page.locator('[data-testid=tab-repository]').count() == 0
    finally:
        gitlab.delete_project(project["id"])
