"""E2E browser: chat do editor com streaming, fila e interrupção (tasks 5.5/5.8).

Stack roda com APPAIFORGE_HARNESS_MODE=fake — eventos determinísticos, sem LLM.
O FakeHarness escreve uma app real no workspace; o supervisor do container a
serve, então a rota /apps/<slug> responde ao fim do chat.
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


def _wait_system_active(page, timeout_ms: int = 60_000) -> None:
    # a aba "Chat" fica sempre visível ao carregar a página, independente de
    # estar selecionada — melhor sinal de "página do sistema renderizou" do
    # que um texto que agora vive dentro de uma aba inativa por padrão
    page.get_by_role("tab", name="Chat").wait_for(timeout=timeout_ms)
    deadline = timeout_ms / 1000
    import time

    start = time.time()
    while time.time() - start < deadline:
        badges = page.locator(".q-badge").all_inner_texts()
        if "ativo" in badges:
            return
        if "erro" in badges:
            raise AssertionError("sistema entrou em erro durante provisionamento")
        page.wait_for_timeout(1000)
    raise AssertionError(f"provisionamento não concluiu em {deadline}s")


def test_chat_gera_app_e_registra_uso_e_checkpoint(page, suffix):
    editor_email = f"chat-editor-{suffix}@e2e.local"
    slug = f"chat-{suffix}"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Chat")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # chat: envia pedido e acompanha o streaming de eventos
    page.locator('[data-testid=chat-input]').fill("crie o painel de clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("Entendi o pedido").wait_for(timeout=30_000)
    page.get_by_text("app/main.py").first.wait_for(timeout=30_000)
    page.get_by_text("agente livre").wait_for(timeout=30_000)

    # uso de tokens visível no painel (fake: 120/80); painel atualiza a cada 2s
    page.get_by_role("tab", name="Auditoria").click()
    page.get_by_text("total: 120 entrada / 80 saída").wait_for(timeout=30_000)

    # checkpoint criado ao fim da execução bem-sucedida
    page.get_by_role("tab", name="Checkpoints").click()
    page.get_by_role("button", name="Restaurar").first.wait_for(timeout=30_000)

    # a app gerada (fake) está no ar pela rota do portal (entrada autenticada)
    import time

    last = None
    for _ in range(30):
        resp = page.request.get(f"/entry/{slug}")
        last = (resp.status, resp.text()[:80])
        if resp.ok and "App de exemplo" in resp.text():
            break
        time.sleep(1)
    else:
        raise AssertionError(f"app de {slug} não ficou no ar em /apps/{slug}; último={last}")


def test_editor_interrompe_execucao(page, suffix):
    editor_email = f"int-editor-{suffix}@e2e.local"
    slug = f"int-{suffix}"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Interrupção")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # envia e interrompe logo em seguida (fake delay dá a janela)
    page.locator('[data-testid=chat-input]').fill("trabalho longo")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_role("button", name="Interromper").wait_for(timeout=30_000, state="visible")
    page.get_by_role("button", name="Interromper").click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)

    # a execução consta como interrompida no histórico
    page.get_by_text("Execuções anteriores").click()
    page.get_by_text("interrompida").first.wait_for(timeout=30_000)


def test_rota_publicada_ao_criar_e_removida_ao_arquivar(page, suffix):
    """Task 6.2: /apps/<slug> publicada quando o sistema ativa e removida ao arquivar."""
    import time

    editor_email = f"route-editor-{suffix}@e2e.local"
    slug = f"route-{suffix}"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")

    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Rota")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # publicada: placeholder responde (via entrada autenticada) enquanto a app não existe
    for _ in range(20):
        resp = page.request.get(f"/entry/{slug}")
        if resp.ok and "ainda nao gerada" in resp.text():
            break
        time.sleep(1)
    else:
        raise AssertionError("rota da app não publicada após provisionamento")

    # arquivada: rota removida (acesso direto sem sessão vira 404 no edge do stack de teste)
    page.get_by_role("button", name="Arquivar sistema").click()
    page.wait_for_timeout(2000)
    last_error = None
    for _ in range(15):
        resp = page.request.get(f"/apps/{slug}/")
        if resp.status == 404:
            return
        last_error = f"HTTP {resp.status}"
        time.sleep(1)
    raise AssertionError(last_error or "rota não removida após arquivamento")
