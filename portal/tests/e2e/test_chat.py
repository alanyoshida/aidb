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

    # chat: envia pedido e acompanha o streaming de eventos; "arquivo alterado"
    # é detalhe técnico e só aparece com o debug ligado (spec agent-harness)
    page.locator('[data-testid=chat-debug]').click()
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

    # excluir o checkpoint (com confirmação) esvazia a timeline
    page.locator('[data-testid=checkpoint-delete]').first.click()
    page.locator('[data-testid=confirm-checkpoint-delete]').click()
    page.get_by_text("Nenhum checkpoint ainda.").wait_for(timeout=30_000)

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

    # a execução consta como interrompida (marcador de transição no log do chat)
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
    page.get_by_role("tab", name="Configurações").click()
    page.get_by_role("button", name="Arquivar sistema").wait_for(timeout=10_000)
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


def test_chat_debug_mostra_comandos(page, suffix):
    """Modo debug: comandos executados só aparecem com o switch ligado (padrão desligado)."""
    editor_email = f"dbg-editor-{suffix}@e2e.local"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Debug")
    page.locator('[data-testid=system-slug]').fill(f"dbg-{suffix}")
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # desligado por padrão: comando não aparece
    page.locator('[data-testid=chat-input]').fill("crie o painel de clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)
    assert not page.get_by_text("comando:").first.is_visible()

    # liga o debug e roda de novo: comandos aparecem
    page.locator('[data-testid=chat-debug]').click()
    page.locator('[data-testid=chat-input]').fill("gere novamente o painel")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)
    page.get_by_text("comando:").first.wait_for(state="visible", timeout=30_000)


def test_sessao_com_contexto_reiniciado_fica_bloqueada(page, suffix):
    """Trocar pra uma sessão cujo contexto foi reiniciado (container
    recriado — ex.: cadastro de conexão, troca de provedor) bloqueia o
    envio de mensagem em vez de deixar o campo aberto com um contexto que
    na verdade já foi descartado (achado real do operador: a sessão
    parecia "continuar" mas o agente começava do zero). O botão "Nova
    sessão" continua disponível e reabre o chat normalmente."""
    import time

    editor_email = f"ctxreset-editor-{suffix}@e2e.local"
    slug = f"ctxreset-{suffix}"
    _create_editor(page, editor_email)
    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Reset de Contexto")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    # primeira mensagem cria a sessão implicitamente; o campo de envio
    # começa habilitado (sem sessão ativa ainda não há nada pra bloquear)
    assert not page.locator('[data-testid=chat-input]').is_disabled()
    session_title = "sessão antes do reset de contexto"
    page.locator('[data-testid=chat-input]').fill(session_title)
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("agente livre").wait_for(timeout=30_000)

    # cadastrar uma conexão recria o container do sistema por baixo, o que
    # invalida (context_reset) todas as sessões abertas dele
    page.get_by_role("tab", name="Conexões").click()
    page.get_by_role("button", name="Nova conexão").click()
    page.locator('[data-testid=conn-name]').wait_for(state="visible", timeout=30_000)
    page.locator('[data-testid=conn-name]').fill("vendas")
    page.locator('[data-testid=conn-host]').fill("postgres")
    page.locator('[data-testid=conn-port]').fill("5432")
    page.locator('[data-testid=conn-database]').fill("appaiforge2")
    page.locator('[data-testid=conn-user]').fill("appaiforge")
    page.locator('[data-testid=conn-password]').fill("appaiforge")
    page.locator('[data-testid=save-connection]').click()
    page.get_by_text("conexão cadastrada").wait_for(timeout=20_000)

    # recarrega a página e reabre a sessão: a recriação do container roda
    # numa thread em segundo plano (recria o container principal e os dois
    # sidecars), então tenta de novo por até 120s
    deadline = time.time() + 120
    blocked_visible = False
    while time.time() < deadline:
        page.reload()
        page.get_by_role("tab", name="Chat").click()
        page.get_by_text("Sessões").click()
        page.get_by_text(session_title, exact=True).click()
        if page.get_by_text("Contexto do agente foi reiniciado").is_visible():
            blocked_visible = True
            break
        page.wait_for_timeout(1000)
    assert blocked_visible, "sessão não ficou bloqueada após recriação do container em 120s"
    assert page.locator('[data-testid=chat-input]').is_disabled()
    assert page.locator('[data-testid=chat-send]').is_disabled()

    # "Nova sessão" sempre disponível, independente do bloqueio — reabre o chat
    page.locator('[data-testid=chat-new-session]').click()
    page.get_by_text("Contexto do agente foi reiniciado").wait_for(state="hidden", timeout=10_000)
    assert not page.locator('[data-testid=chat-input]').is_disabled()
    assert not page.locator('[data-testid=chat-send]').is_disabled()
