"""E2E browser: administração de usuários e grupos + portões de papel (task 2.3).

Usa o admin semeado pelo stack de teste (admin@appaiforge.local / admin123).
Nomes usam sufixo único por execução: o banco do stack é persistente e os
testes precisam ser idempotentes.
No NiceGUI 3.x, props data-testid caem no próprio <input> nativo.
"""

import uuid

import pytest

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture()
def suffix() -> str:
    return uuid.uuid4().hex[:8]


def _login(page, email: str, password: str) -> None:
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill(email)
    page.locator('[data-testid=login-password]').fill(password)
    page.get_by_role("button", name="Entrar").click()
    page.get_by_text(email).first.wait_for(timeout=30_000)


def _logout(page) -> None:
    page.get_by_role("button", name="Sair").click()
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def _create_user(page, email: str, password: str, user_type: str) -> None:
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill(password)
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text(user_type, exact=True).click()
    page.locator('[data-testid=create-user]').click()


def test_admin_gerencia_usuarios_grupos_e_papéis(page, suffix):
    editor_email = f"editor-{suffix}@e2e.local"
    app_email = f"app-{suffix}@e2e.local"
    group_name = f"equipe-{suffix}"

    # admin loga e abre a administração
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()

    # cria um editor e um app_user
    _create_user(page, editor_email, "pw-editor", "editor")
    page.get_by_text(editor_email).first.wait_for(timeout=30_000)
    _create_user(page, app_email, "pw-app", "app_user")
    page.get_by_text(app_email).first.wait_for(timeout=30_000)

    # grupo + membro
    page.get_by_role("tab", name="Grupos").click()
    page.locator('[data-testid=new-group-name]').fill(group_name)
    page.locator('[data-testid=create-group]').click()
    page.get_by_text(f"membros: —", exact=False).first.wait_for(timeout=30_000)
    page.locator('[data-testid=member-group]').fill(group_name)
    page.locator('[data-testid=member-email]').fill(app_email)
    page.locator('[data-testid=add-member]').click()
    page.get_by_text(f"membros: {app_email}").wait_for(timeout=30_000)

    _logout(page)

    # editor vê o botão de criar sistema; app_user não vê nada
    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").wait_for(timeout=30_000)
    _logout(page)

    _login(page, app_email, "pw-app")
    page.get_by_text("Nenhum sistema acessível.").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Novo sistema").count() == 0
    assert page.get_by_role("button", name="Administração").count() == 0


def test_login_invalido_mostra_mensagem_generica(page):
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill("admin@appaiforge.local")
    page.locator('[data-testid=login-password]').fill("senha-torta")
    page.get_by_role("button", name="Entrar").click()
    page.get_by_text("E-mail ou senha inválidos.").wait_for(timeout=30_000)
