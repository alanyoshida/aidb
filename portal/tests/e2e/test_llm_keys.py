"""E2E browser: gestão de chaves e catálogo de provedores de LLM pelo admin (tasks 4.1, 6.1)."""

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
    page.locator('[data-testid=user-menu]').wait_for(timeout=30_000)


def _card(page, text: str):
    return page.locator(f'[data-testid="key-card:{text}"]').first


def test_admin_cadastra_e_remove_chave(page):
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Provedores de LLM").click()

    card = _card(page, "glm")
    card.wait_for(timeout=30_000)
    card.get_by_role("button", name="Cadastrar/Trocar").click()
    page.locator('[data-testid=key-input]').fill("chave-teste-e2e")
    page.locator('[data-testid=confirm-key-set]').click()
    card.get_by_text("configurada").wait_for(timeout=30_000)

    card.get_by_role("button", name="Remover").click()
    page.locator('[data-testid=confirm-key-remove]').click()
    card.get_by_text("sem chave").wait_for(timeout=30_000)


def test_testar_provedor_sem_chave(page):
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Provedores de LLM").click()

    card = _card(page, "anthropic")
    card.wait_for(timeout=30_000)
    card.get_by_role("button", name="Testar").click()
    page.get_by_text("chave não configurada").wait_for(timeout=30_000)


def test_admin_gerencia_provedor_custom(page, suffix):
    provider = f"custom-{suffix}"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Provedores de LLM").click()

    page.locator('[data-testid=provider-new]').click()
    page.locator('[data-testid=provider-id]').fill(provider)
    page.locator('[data-testid=provider-label]').fill("Custom E2E")
    page.locator('[data-testid=provider-base-url]').fill("http://127.0.0.1:9/v1")
    page.locator('[data-testid=confirm-provider-create]').click()

    card = _card(page, provider)
    card.wait_for(timeout=30_000)

    # busca de modelos na rota do provedor (aqui inacessível: não derruba a tela)
    card.get_by_role("button", name="Buscar modelos").click()
    page.get_by_text(f"{provider}:").first.wait_for(timeout=30_000)

    # edita o rótulo
    card.get_by_role("button", name="Editar").click()
    page.locator('[data-testid=provider-edit-label]').fill("Custom E2E 2")
    page.locator('[data-testid=confirm-provider-edit]').click()
    card.get_by_text("Custom E2E 2").wait_for(timeout=30_000)

    # remove o provedor custom
    card.get_by_role("button", name="Excluir provedor").click()
    page.locator('[data-testid=confirm-provider-remove]').click()
    page.locator(f'[data-testid="key-card:{provider}"]').wait_for(state="detached", timeout=30_000)