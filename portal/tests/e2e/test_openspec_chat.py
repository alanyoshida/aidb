"""E2E (harness fake): OpenSpec no workspace do sistema e autocomplete de comandos no chat
(change add-openspec-to-system-container, tasks 4.4 e 5.1).

O harness fake lista os comandos lendo `.opencode/commands/` do workspace — os mesmos arquivos que
o supervisor do container cria com `openspec init` ao subir o sistema.
"""

import uuid

import docker
import pytest

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"
OPSX = ("opsx-apply", "opsx-archive", "opsx-explore", "opsx-propose")


def _login(page) -> None:
    page.goto("/login")
    page.locator("[data-testid=login-email]").fill(ADMIN_EMAIL)
    page.locator("[data-testid=login-password]").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Entrar").click()
    page.locator("[data-testid=user-menu]").wait_for(timeout=30_000)


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


def _workspace_has(slug: str, path: str) -> bool:
    container = docker.from_env().containers.get(f"appaiforge-sys-{slug}")
    return container.exec_run(["test", "-f", f"/workspace/{path}"]).exit_code == 0


@pytest.fixture()
def chat(page):
    slug = f"ospec-{uuid.uuid4().hex[:8]}"
    _login(page)
    page.get_by_role("button", name="Novo sistema").click()
    page.locator("[data-testid=system-name]").fill("Sistema OpenSpec")
    page.locator("[data-testid=system-slug]").fill(slug)
    page.locator("[data-testid=create-system]").click()
    _wait_system_active(page)
    for _ in range(60):
        if _workspace_has(slug, ".opencode/commands/opsx-propose.md"):
            break
        page.wait_for_timeout(1000)
    page.get_by_role("tab", name="Chat").click()
    page.locator("[data-testid=chat-input]").wait_for(timeout=30_000)
    return {"slug": slug, "page": page}


def _menu(page):
    return page.locator("[data-testid=chat-command-menu]")


def test_workspace_sobe_com_openspec_configurado(chat):
    slug = chat["slug"]
    assert _workspace_has(slug, "openspec/config.yaml")
    for name in OPSX:
        assert _workspace_has(slug, f".opencode/commands/{name}.md")


def test_barra_mostra_comandos_com_descricao(chat):
    page = chat["page"]
    page.locator("[data-testid=chat-input]").fill("/")
    _menu(page).wait_for(state="visible", timeout=15_000)
    for name in OPSX:
        item = page.locator(f'[data-testid="chat-command:{name}"]')
        item.wait_for(timeout=10_000)
        assert item.locator(".af-cmd-desc").inner_text().strip()


def test_filtro_pelo_prefixo(chat):
    page = chat["page"]
    page.locator("[data-testid=chat-input]").fill("/opsx-ap")
    page.locator('[data-testid="chat-command:opsx-apply"]').wait_for(timeout=15_000)
    assert page.locator('[data-testid="chat-command:opsx-propose"]').count() == 0


def test_escolha_pelo_teclado_completa_sem_enviar(chat):
    page = chat["page"]
    field = page.locator("[data-testid=chat-input]")
    field.fill("/opsx-")
    page.locator('[data-testid="chat-command:opsx-apply"]').wait_for(timeout=15_000)
    field.press("ArrowDown")  # opsx-apply -> opsx-archive
    page.locator('[data-testid="chat-command:opsx-archive"][aria-selected=true]').wait_for(timeout=10_000)
    field.press("Enter")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=chat-input]').value === '/opsx-archive '",
        timeout=10_000,
    )
    _menu(page).wait_for(state="hidden", timeout=10_000)
    assert page.get_by_text("agente executando").count() == 0  # nada foi enviado

    field.fill("/opsx-pr")
    page.locator('[data-testid="chat-command:opsx-propose"]').wait_for(timeout=15_000)
    field.press("Tab")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=chat-input]').value === '/opsx-propose '",
        timeout=10_000,
    )

    field.fill("/opsx-")
    _menu(page).wait_for(state="visible", timeout=15_000)
    field.press("Escape")
    _menu(page).wait_for(state="hidden", timeout=10_000)


def test_texto_sem_barra_nao_sugere_e_enter_envia(chat):
    page = chat["page"]
    field = page.locator("[data-testid=chat-input]")
    field.fill("crie o painel de clientes")
    page.wait_for_timeout(1500)
    assert not _menu(page).is_visible()
    # com o menu fechado, Enter envia como sempre (inclusive um comando já completo com argumentos)
    field.fill("/opsx-propose adicionar filtro por data")
    page.wait_for_timeout(800)
    assert not _menu(page).is_visible()
    field.press("Enter")
    page.get_by_text("adicionar filtro por data").first.wait_for(timeout=30_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)
