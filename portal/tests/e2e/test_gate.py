"""E2E browser: gate de operações destrutivas (tasks 3.1, 3.2, 5.1).

Cenários via harness fake: TRUNCATE é recusado automaticamente (sem botão);
DELETE em massa aguarda aprovação no chat; recusa do editor notifica o agente;
histórico do gate aparece na página do sistema.
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
    page.locator('[data-testid=user-menu]').wait_for(timeout=30_000)


def _logout(page) -> None:
    page.locator('[data-testid=user-menu]').click()
    page.locator('[data-testid=logout]').click()
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def _create_system(page, suffix: str) -> str:
    editor_email = f"gate-editor-{suffix}@e2e.local"
    # admin cria o editor
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(editor_email)
    page.locator('[data-testid=new-user-password]').fill("pw-gate")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(editor_email).first.wait_for(timeout=30_000)
    _logout(page)

    # editor cria o sistema e agrega a conexão de teste do stack
    _login(page, editor_email, "pw-gate")
    page.get_by_role("button", name="Novo sistema").click()
    slug = f"gate-{suffix}"
    page.locator('[data-testid=system-name]').fill("Sistema Gate")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    # a aba "Chat" fica sempre visível ao carregar a página, independente de
    # estar selecionada — melhor sinal de "página do sistema renderizou" do
    # que um texto que agora vive dentro de uma aba inativa por padrão
    page.get_by_role("tab", name="Chat").wait_for(timeout=60_000)
    import time

    start = time.time()
    while time.time() - start < 60:
        if "ativo" in page.locator(".q-badge").all_inner_texts():
            return slug
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def _chat(page, message: str) -> None:
    page.locator('[data-testid=chat-input]').fill(message)
    page.locator('[data-testid=chat-send]').click()


def test_gate_truncate_bloqueado_e_delete_aprovado(page, suffix):
    slug = _create_system(page, suffix)

    # 1) TRUNCATE: recusa automática, sem painel de aprovação
    _chat(page, "por favor TRUNCATE a tabela clientes")
    page.get_by_text("bloqueada pelo gate").wait_for(timeout=60_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)
    page.get_by_role("button", name="Aprovar").count() == 0

    # 2) DELETE em massa: painel de aprovação, editor aprova
    _chat(page, "agora DELETE SEM WHERE na tabela clientes")
    page.get_by_text("PEDIDO DE APROVAÇÃO").wait_for(timeout=60_000)
    page.get_by_role("button", name="Aprovar").click()
    page.get_by_text("aprovada pelo editor").wait_for(timeout=60_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)

    # 3) histórico do gate mostra bloqueada e aprovada (painel atualiza a cada 2s)
    page.get_by_role("tab", name="Auditoria").click()
    page.get_by_text("Gate de destrutivas").wait_for(timeout=30_000)
    page.get_by_text("Ações de gestão").wait_for(timeout=30_000)
    page.get_by_text("[bloqueada]").first.wait_for(timeout=30_000)
    page.get_by_text("[aprovada]").first.wait_for(timeout=30_000)


def test_gate_recusa_do_editor(page, suffix):
    slug = _create_system(page, suffix)

    _chat(page, "agora DELETE SEM WHERE na tabela clientes")
    page.get_by_text("PEDIDO DE APROVAÇÃO").wait_for(timeout=60_000)
    page.get_by_role("button", name="Recusar").click()
    page.get_by_text("recusada pelo editor").wait_for(timeout=60_000)
    page.get_by_text("agente livre").wait_for(timeout=60_000)

    body = page.inner_text("body")
    assert "recusada pelo gate" in body or "recusada: execução interrompida" in body or "[recusada]" in body
    page.get_by_role("tab", name="Auditoria").click()
    page.get_by_text("Gate de destrutivas").wait_for(timeout=30_000)
    page.get_by_text("[recusada]").first.wait_for(timeout=30_000)
