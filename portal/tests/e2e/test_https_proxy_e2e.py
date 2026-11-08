"""E2E browser: controles de rede do proxy HTTP(S) de saída (change
`agent-https-forward-proxy`, task 6.6) — cobre a UI (aba Configurações: os
dois toggles; aba Domínios: lista + adicionar). A conectividade de verdade
através do proxy (CONNECT permitido/recusado, Landlock negando 443 direto)
já está provada em `tests/integration/test_https_proxy.py` contra Docker
real — o harness fake deste stack não executa bash nenhum, então não há
como disparar tráfego de rede de dentro do container por uma mensagem de
chat; este teste cobre só o que falta: a UI liga/desliga os controles e
edita a lista de verdade, persistindo no sistema certo."""

import os
import time
import uuid

import pytest

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"
BASE_URL = os.environ.get("APPAIFORGE_E2E_BASE_URL", "http://localhost:8081").rstrip("/")


@pytest.fixture()
def suffix() -> str:
    return uuid.uuid4().hex[:8]


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


def _create_system(page, suffix: str) -> str:
    editor_email = f"httpsproxy-e2e-{suffix}@e2e.local"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(editor_email)
    page.locator('[data-testid=new-user-password]').fill("pw-httpsproxy")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(editor_email).first.wait_for(timeout=30_000)
    _logout(page)

    _login(page, editor_email, "pw-httpsproxy")
    page.get_by_role("button", name="Novo sistema").click()
    slug = f"httpsproxy-{suffix}"
    page.locator('[data-testid=system-name]').fill("Sistema HTTPS Proxy E2E")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_role("tab", name="Chat").wait_for(timeout=60_000)

    deadline = time.time() + 60
    while time.time() < deadline:
        if "ativo" in page.locator(".q-badge").all_inner_texts():
            return slug
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def test_toggles_e_lista_de_dominios_pela_ui(page, suffix):
    _create_system(page, suffix)

    page.get_by_role("tab", name="Domínios").click()
    # a lista nasce pré-populada (task 4.2) — mesmo sem nunca ligar o modo restrito
    page.locator('[data-testid=domain-item]').first.wait_for(timeout=30_000)
    pre_populated = page.locator('[data-testid=domain-item]').all_inner_texts()
    assert {"pypi.org", "files.pythonhosted.org", "registry.npmjs.org"} <= set(pre_populated)

    page.locator('[data-testid=new-domain]').fill("minha-api.e2e.local")
    page.locator('[data-testid=add-domain]').click()
    page.get_by_text("minha-api.e2e.local").wait_for(timeout=10_000)

    page.get_by_role("tab", name="Configurações").click()
    internet_switch = page.locator('[data-testid=toggle-internet-enabled]')
    restricted_switch = page.locator('[data-testid=toggle-restricted-network]')
    internet_switch.wait_for(timeout=10_000)

    # padrão: internet ligada, modo restrito desligado
    assert internet_switch.get_attribute("aria-checked") == "true"
    assert restricted_switch.get_attribute("aria-checked") == "false"

    restricted_switch.click()
    page.get_by_text("Modo restrito ligado").wait_for(timeout=10_000)
    assert restricted_switch.get_attribute("aria-checked") == "true"

    internet_switch.click()
    page.get_by_text("Acesso à internet desabilitado").wait_for(timeout=10_000)
    assert internet_switch.get_attribute("aria-checked") == "false"

    # recarrega a página: os dois controles persistiram (não é só estado do widget)
    page.reload()
    page.get_by_role("tab", name="Configurações").click()
    internet_switch = page.locator('[data-testid=toggle-internet-enabled]')
    restricted_switch = page.locator('[data-testid=toggle-restricted-network]')
    internet_switch.wait_for(timeout=10_000)
    assert internet_switch.get_attribute("aria-checked") == "false"
    assert restricted_switch.get_attribute("aria-checked") == "true"
