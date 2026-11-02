"""E2E browser: criação de sistema e cadastro de conexões (task 3.4).

O alvo das conexões é o próprio Postgres do stack (host "postgres" na rede
interna, databases appaiforge e appaiforge2) — o portal container alcança.
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


def _create_editor_via_admin(page, email: str) -> None:
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-editor")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)
    _logout(page)


def _fill_connection(page, name: str, database: str, password: str) -> None:
    page.locator('[data-testid=conn-name]').fill(name)
    page.locator('[data-testid=conn-host]').fill("postgres")
    page.locator('[data-testid=conn-port]').fill("5432")
    page.locator('[data-testid=conn-database]').fill(database)
    page.locator('[data-testid=conn-user]').fill("appaiforge")
    page.locator('[data-testid=conn-password]').fill(password)
    page.locator('[data-testid=save-connection]').click()


def test_editor_cria_sistema_e_cadastra_duas_conexoes(page, suffix):
    editor_email = f"sys-editor-{suffix}@e2e.local"
    slug = f"sys-{suffix}"
    _create_editor_via_admin(page, editor_email)

    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema E2E")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()

    # detalhe do sistema carrega
    page.get_by_text("Conexões de banco").wait_for(timeout=30_000)

    # conexão inválida é recusada com feedback
    _fill_connection(page, "errada", "appaiforge", "senha-torta")
    page.get_by_text("teste de conexão falhou").wait_for(timeout=30_000)

    # duas conexões válidas a bancos distintos são aceitas
    _fill_connection(page, "vendas", "appaiforge", "appaiforge")
    page.get_by_text("conexão cadastrada").wait_for(timeout=20_000)
    page.get_by_text("appaiforge@postgres:5432/appaiforge").wait_for(timeout=30_000)

    _fill_connection(page, "fiscal", "appaiforge2", "appaiforge")
    page.get_by_text("appaiforge@postgres:5432/appaiforge2").wait_for(timeout=30_000)

    # nenhuma senha aparece na tela
    content = page.content()
    assert "senha-torta" not in content


def test_slug_duplicado_mostra_feedback(page, suffix):
    editor_email = f"slug-editor-{suffix}@e2e.local"
    slug = f"dupsys-{suffix}"
    _create_editor_via_admin(page, editor_email)

    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Primeiro")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_text("Conexões de banco").wait_for(timeout=30_000)

    page.goto("/systems/new")
    page.locator('[data-testid=system-name]').fill("Segundo")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_text("já existe").wait_for(timeout=30_000)
