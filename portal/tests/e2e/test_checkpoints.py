"""E2E browser: aba Checkpoints com restauração que preserva o histórico (change
`isolate-workspace-repository`; spec agent-harness, requirement "Checkpoints git por execução").

Stack fake: a primeira execução gera a app; uma execução com "anote ..." também grava
`notas.txt`, o que dá dois checkpoints com conteúdo diferente para restaurar pela interface.
"""

import time
import uuid

import pytest

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


def _create_editor(page, email: str) -> None:
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-editor")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)
    _logout(page)


def _wait_system_active(page, timeout_s: int = 60) -> None:
    page.get_by_role("tab", name="Chat").wait_for(timeout=timeout_s * 1000)
    start = time.time()
    while time.time() - start < timeout_s:
        badges = page.locator(".q-badge").all_inner_texts()
        if "ativo" in badges:
            return
        if "erro" in badges:
            raise AssertionError("sistema entrou em erro durante provisionamento")
        page.wait_for_timeout(1000)
    raise AssertionError(f"provisionamento não concluiu em {timeout_s}s")


def _send(page, prompt: str) -> None:
    page.get_by_role("tab", name="Chat").click()
    page.locator('[data-testid=chat-input]').fill(prompt)
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text(f"Entendi o pedido: {prompt}").wait_for(timeout=30_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)


def _entries(page, origin: str):
    return page.locator(f'[data-testid="checkpoint-entry:{origin}"]')


def test_restaurar_checkpoint_anterior_cria_entrada_de_restauracao(page):
    suffix = uuid.uuid4().hex[:8]
    editor_email = f"ckpt-editor-{suffix}@e2e.local"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Checkpoints")
    page.locator('[data-testid=system-slug]').fill(f"ckpt-{suffix}")
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    _send(page, "crie o painel de clientes")
    _send(page, "anote revisar a busca")

    page.get_by_role("tab", name="Checkpoints").click()
    runs = _entries(page, "run")
    runs.nth(1).wait_for(timeout=30_000)
    assert runs.count() == 2
    assert "execução do agente" in runs.first.inner_text().lower()  # o tema usa caixa alta

    # restaurar o checkpoint mais recente não muda nada
    runs.first.get_by_role("button", name="Restaurar").click()
    page.get_by_text("Nada a restaurar").wait_for(timeout=30_000)
    assert _entries(page, "restore").count() == 0

    # restaurar o mais antigo cria uma entrada de restauração e mantém as duas anteriores
    runs.last.get_by_role("button", name="Restaurar").click()
    page.get_by_text("workspace restaurado").wait_for(timeout=30_000)
    restores = _entries(page, "restore")
    restores.first.wait_for(timeout=30_000)
    assert restores.count() == 1
    assert "restauração" in restores.first.inner_text().lower()
    assert _entries(page, "run").count() == 2

    # o checkpoint posterior continua restaurável
    _entries(page, "run").first.get_by_role("button", name="Restaurar").click()
    page.get_by_text("workspace restaurado").last.wait_for(timeout=30_000)
    for _ in range(30):
        if _entries(page, "restore").count() == 2:
            break
        page.wait_for_timeout(1000)
    assert _entries(page, "restore").count() == 2

    # checkpoint manual sem alteração nenhuma
    page.get_by_role("button", name="Criar checkpoint agora").click()
    page.get_by_text("Nada mudou no workspace").wait_for(timeout=30_000)
