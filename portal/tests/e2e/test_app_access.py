"""E2E (stack local): acesso às apps verificado pelo edge e break-glass (change add-oidc-sso, tasks 3.3/6.5).

- link direto para a app sem sessão -> login -> volta ao endereço da app;
- usuário sem acesso -> 403 do portal;
- logout derruba a app que estava aberta;
- `X-AIDB-Identity` forjado pelo cliente nunca chega à app;
- break-glass entra por /login/local e vê o aviso de sessão de emergência.
"""

import uuid

import os

import httpx
import pytest

BASE_URL = os.environ.get("APPAIFORGE_E2E_BASE_URL", "http://localhost:8081").rstrip("/")

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"
BREAKGLASS_EMAIL = "breakglass@appaiforge.local"
BREAKGLASS_PASSWORD = "bg-e2e-senha"  # definido em deploy/docker-compose.e2e.yml


@pytest.fixture()
def suffix() -> str:
    return uuid.uuid4().hex[:8]


def _fill_login(page, email: str, password: str) -> None:
    page.locator("[data-testid=login-email]").fill(email)
    page.locator("[data-testid=login-password]").fill(password)
    page.get_by_role("button", name="Entrar").click()


def _login(page, email: str, password: str) -> None:
    page.goto("/login")
    _fill_login(page, email, password)
    page.locator("[data-testid=user-menu]").wait_for(timeout=30_000)


def _logout(page) -> None:
    page.goto("/auth/logout")
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def _create_user(page, email: str, user_type: str, password: str) -> None:
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator("[data-testid=new-user-email]").fill(email)
    page.locator("[data-testid=new-user-password]").fill(password)
    page.locator("[data-testid=new-user-type]").click()
    page.locator(".q-menu:visible").get_by_text(user_type, exact=True).click()
    page.locator("[data-testid=create-user]").click()
    page.get_by_text(email).first.wait_for(timeout=30_000)


def _wait_system_active(page) -> None:
    page.get_by_role("tab", name="Chat").wait_for(timeout=60_000)
    for _ in range(60):
        badges = page.locator(".q-badge").all_inner_texts()
        if "ativo" in badges:
            return
        if "erro" in badges:
            raise AssertionError("sistema em erro")
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def _wait_app(page, slug: str) -> None:
    for _ in range(30):
        resp = page.request.get(f"/apps/{slug}/")
        if resp.ok and "ainda nao gerada" in resp.text():
            return
        page.wait_for_timeout(1000)
    raise AssertionError(f"app de {slug} não ficou no ar")


@pytest.fixture()
def system(page, suffix):
    """Editor e2e + sistema ativo (placeholder no ar) + app_user sem vínculo."""
    editor = f"acc-editor-{suffix}@e2e.local"
    outsider = f"acc-fora-{suffix}@e2e.local"
    slug = f"acc-{suffix}"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    _create_user(page, editor, "editor", "pw-acc")
    _create_user(page, outsider, "app_user", "pw-acc")
    _logout(page)
    _login(page, editor, "pw-acc")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator("[data-testid=system-name]").fill("Sistema Acesso")
    page.locator("[data-testid=system-slug]").fill(slug)
    page.locator("[data-testid=create-system]").click()
    _wait_system_active(page)
    _wait_app(page, slug)
    _logout(page)
    return {"slug": slug, "editor": editor, "outsider": outsider}


def test_link_direto_sem_sessao_volta_a_app_apos_login(page, system):
    slug = system["slug"]
    page.goto(f"/apps/{slug}/relatorios?mes=3")
    page.wait_for_url("**/login?next=*", timeout=30_000)
    _fill_login(page, system["editor"], "pw-acc")
    page.wait_for_url(f"**/apps/{slug}/relatorios?mes=3", timeout=30_000)
    assert "ainda nao gerada" in page.inner_text("body")


def test_usuario_sem_acesso_recebe_403(page, system):
    _login(page, system["outsider"], "pw-acc")
    resp = page.goto(f"/apps/{system['slug']}/")
    assert resp.status == 403
    assert "Permissão insuficiente" in page.inner_text("body")


def test_logout_derruba_a_app_aberta(page, system):
    slug = system["slug"]
    _login(page, system["editor"], "pw-acc")
    page.goto(f"/apps/{slug}/")
    assert "ainda nao gerada" in page.inner_text("body")
    _logout(page)
    page.goto(f"/apps/{slug}/")
    page.wait_for_url("**/login?next=*", timeout=30_000)


def test_identidade_forjada_nao_chega_a_app(page, system):
    slug = system["slug"]
    forged = {"X-AIDB-Identity": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.forjado"}
    # sem sessão: o header forjado não abre a app — o edge manda ao login
    r = httpx.get(f"{BASE_URL}/apps/{slug}/", headers=forged, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(f"{BASE_URL}/login?next=")
    # com sessão: a app recebe a identidade emitida pelo portal, não a forjada
    _login(page, system["editor"], "pw-acc")
    resp = page.request.get(f"/apps/{slug}/", headers=forged)
    assert resp.ok and "ainda nao gerada" in resp.text()


def test_break_glass_entra_e_ve_aviso_de_emergencia(page):
    page.goto("/login/local")
    _fill_login(page, BREAKGLASS_EMAIL, BREAKGLASS_PASSWORD)
    page.locator("[data-testid=breakglass-banner]").wait_for(timeout=30_000)
    page.get_by_role("button", name="Administração").click()
    page.locator("[data-testid=breakglass-banner]").wait_for(timeout=30_000)
    card = page.locator(f'[data-testid="user-card:{BREAKGLASS_EMAIL}"]')
    card.locator("[data-testid=user-breakglass]").wait_for(timeout=30_000)
    assert card.get_by_role("button", name="Excluir").count() == 0
