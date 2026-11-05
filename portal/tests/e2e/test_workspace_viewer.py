"""E2E browser: aba Editor somente-leitura sobre os arquivos do workspace
(tasks 2.5/3.1, capability workspace-viewer).

Stack roda com APPAIFORGE_HARNESS_MODE=fake — o FakeHarness escreve
`app/main.py` de forma determinística no workspace a cada pedido no chat.
"""

import os
import subprocess
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


def _wait_system_active(page, timeout_ms: int = 60_000) -> None:
    page.get_by_role("tab", name="Chat").wait_for(timeout=timeout_ms)
    import time

    deadline = timeout_ms / 1000
    start = time.time()
    while time.time() - start < deadline:
        badges = page.locator(".q-badge").all_inner_texts()
        if "ativo" in badges:
            return
        if "erro" in badges:
            raise AssertionError("sistema entrou em erro durante provisionamento")
        page.wait_for_timeout(1000)
    raise AssertionError(f"provisionamento não concluiu em {deadline}s")


def test_editor_reflete_workspace_somente_leitura(page, suffix):
    """Árvore vazia antes da geração, aparece depois (via polling, sem
    recarregar a página), conteúdo com destaque de sintaxe, e digitar no
    painel não altera o conteúdo exibido."""
    slug = f"editor-{suffix}"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Editor")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # antes de qualquer geração: aba Editor informa que não há arquivos ainda
    page.get_by_role("tab", name="Editor").click()
    page.locator('[data-testid=editor-empty]').wait_for(timeout=30_000)

    # pede uma geração pelo chat (FakeHarness grava app/main.py)
    page.get_by_role("tab", name="Chat").click()
    page.locator('[data-testid=chat-input]').fill("crie o painel de clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)

    # volta para o Editor (já estava montado antes da geração) — a árvore
    # se atualiza por polling, sem precisar recarregar a página
    page.get_by_role("tab", name="Editor").click()
    page.locator('[data-testid=editor-tree]').get_by_text("main.py").wait_for(timeout=30_000)
    page.locator('[data-testid=editor-tree]').get_by_text("main.py").click()

    content = page.locator('[data-testid=editor-content]')
    content.get_by_text("App de exemplo gerada pelo FakeHarness", exact=False).wait_for(timeout=30_000)

    # tentativa de digitar no painel não altera o conteúdo exibido
    content.click()
    page.keyboard.type("HACKED")
    content.get_by_text("App de exemplo gerada pelo FakeHarness", exact=False).wait_for(timeout=5_000)
    assert "HACKED" not in content.inner_text()


def test_editor_arvore_atualiza_sem_recarregar_apos_nova_escrita(page, suffix):
    """Task 3.1: depois de um pedido no chat que já deixou a aba Editor
    aberta, um arquivo novo escrito no workspace aparece na árvore sem
    recarregar a página — o FakeHarness é determinístico e sempre escreve o
    mesmo `app/main.py`, então o arquivo novo é escrito direto no workspace
    pelo lado do portal (via `docker exec` no container `portal`, mesmo lado
    de onde o próprio FakeHarness escreve e de onde `workspace_files.py` lê —
    não dentro do container do sistema, que vê o mesmo volume mas com outro
    dono), mas o que esta verificação prova é exatamente o polling da task
    3.1: a árvore se reconstrói sozinha a cada 2s, então enxerga qualquer
    mudança no workspace — não só as que vieram de uma execução do agente."""
    slug = f"editor2-{suffix}"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Editor 2")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    page.get_by_role("tab", name="Editor").click()
    page.locator('[data-testid=editor-empty]').wait_for(timeout=30_000)

    page.get_by_role("tab", name="Chat").click()
    page.locator('[data-testid=chat-input]').fill("crie o painel de clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)

    # volta para o Editor, já aberto antes da geração, e confirma main.py
    page.get_by_role("tab", name="Editor").click()
    page.locator('[data-testid=editor-tree]').get_by_text("main.py").wait_for(timeout=30_000)

    # escreve um segundo arquivo direto no container do portal (fora do
    # chat, mesmo padrão docker exec que conftest.py já usa) — sem sair da
    # aba Editor nem recarregar a página
    portal_container = os.environ.get("APPAIFORGE_E2E_PORTAL_CONTAINER", "appaiforge-e2e-portal-1")
    subprocess.run(
        ["docker", "exec", portal_container, "sh", "-c",
         f"echo '# arquivo escrito depois que o editor já estava aberto' > /workspaces/{slug}/app/extra.py"],
        check=True, timeout=10,
    )

    page.locator('[data-testid=editor-tree]').get_by_text("extra.py").wait_for(timeout=10_000)
