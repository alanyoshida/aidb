"""E2E: jornada ponta a ponta completa (task 7.1).

admin cria usuários/grupos -> editor cria sistema -> conecta Postgres de teste
-> gera app pelo chat (harness fake) -> app_user de grupo usa a app em
/apps/<slug> -> app_user sem vínculo é negado -> rollback por checkpoint na UI.
"""

import time
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


def _select(page, testid: str, text: str) -> None:
    """Escolhe uma opção num ui.select do NiceGUI (menu suspenso).

    Espera o menu anterior fechar antes de abrir o próximo: com opções de texto
    idêntico (ex.: grupo e sistema com o mesmo nome) um clique no menu ainda
    aberto selecionaria o item errado.
    """
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)
    page.locator(f"[data-testid={testid}]").click()
    page.locator(".q-menu:visible").get_by_text(text, exact=True).click()
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)


def _create_user(page, email: str, user_type: str) -> None:
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-jornada")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text(user_type, exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)


def _wait_system_active(page) -> None:
    # a aba "Chat" fica sempre visível ao carregar a página, independente de
    # estar selecionada — melhor sinal de "página do sistema renderizou" do
    # que um texto que agora vive dentro de uma aba inativa por padrão
    page.get_by_role("tab", name="Chat").wait_for(timeout=60_000)
    import time as _time

    start = _time.time()
    while _time.time() - start < 60:
        badges = page.locator(".q-badge").all_inner_texts()
        if "ativo" in badges:
            return
        if "erro" in badges:
            raise AssertionError("sistema em erro")
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def test_jornada_completa(page, suffix):
    editor_email = f"j-editor-{suffix}@e2e.local"
    app_in_email = f"j-appin-{suffix}@e2e.local"
    app_out_email = f"j-appout-{suffix}@e2e.local"
    group_name = f"jornada-{suffix}"
    slug = f"jornada-{suffix}"

    # 1. admin monta o diretório: editor, dois app_users e grupo
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()
    _create_user(page, editor_email, "editor")
    _create_user(page, app_in_email, "app_user")
    _create_user(page, app_out_email, "app_user")
    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Novo grupo").click()
    page.locator('[data-testid=new-group-name]').fill(group_name)
    page.locator('[data-testid=create-group]').click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Adicionar membro a um grupo").click()
    _select(page, "member-group", group_name)
    _select(page, "member-email", app_in_email)
    page.locator('[data-testid=add-member]').click()
    _logout(page)

    # 2. editor cria sistema e conecta o Postgres de teste do stack
    _login(page, editor_email, "pw-jornada")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Jornada")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_system_active(page)

    page.get_by_role("tab", name="Conexões").click()
    page.get_by_role("button", name="Nova conexão").click()
    page.locator('[data-testid=conn-name]').fill("vendas")
    page.locator('[data-testid=conn-host]').fill("postgres")
    page.locator('[data-testid=conn-database]').fill("appaiforge")
    page.locator('[data-testid=conn-user]').fill("appaiforge")
    page.locator('[data-testid=conn-password]').fill("appaiforge")
    page.locator('[data-testid=save-connection]').click()
    page.get_by_text("conexão cadastrada").wait_for(timeout=30_000)
    _logout(page)

    # 2b. admin vincula o grupo ao sistema recém-criado
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Vincular a sistema").click()
    _select(page, "link-group", group_name)
    _select(page, "link-slug", slug)
    page.locator('[data-testid=link-system]').click()
    page.get_by_text(f"sistemas: {slug}").wait_for(timeout=30_000)
    _logout(page)

    # 3. chat gera a app (harness fake) — editor volta ao sistema
    _login(page, editor_email, "pw-jornada")
    page.goto("/")
    page.get_by_text("Sistema Jornada").first.click()
    page.locator('[data-testid=chat-input]').wait_for(timeout=30_000)
    page.locator('[data-testid=chat-input]').fill("gere o admin do sistema")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("Entendi o pedido").wait_for(timeout=30_000)
    page.get_by_text("agente livre").wait_for(timeout=90_000)
    page.wait_for_timeout(3000)  # supervisor reinicia a app com o código gerado

    # 4. app_user DO grupo usa a app com identidade do portal
    _logout(page)
    _login(page, app_in_email, "pw-jornada")
    page.goto(f"/entry/{slug}")
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    assert "App de exemplo" in body, f"app_user do grupo não alcançou a app: {body[:200]}"
    page.goto("/")
    _logout(page)

    # 5. app_user SEM vínculo é negado (na entrada e direto na app)
    _login(page, app_out_email, "pw-jornada")
    page.goto(f"/entry/{slug}")
    page.get_by_text("Nenhum sistema acessível.").wait_for(timeout=30_000)
    page.goto(f"/apps/{slug}/")
    page.wait_for_timeout(1500)
    assert "App de exemplo" not in page.inner_text("body")
    assert "acesso restrito" in page.inner_text("body")
    page.goto("/")
    _logout(page)

    # 6. rollback por checkpoint na UI
    _login(page, editor_email, "pw-jornada")
    page.goto("/")
    page.get_by_text("Sistema Jornada").first.click()
    page.get_by_role("tab", name="Checkpoints").click()
    page.get_by_role("button", name="Restaurar").first.click()
    page.get_by_text("workspace restaurado").wait_for(timeout=30_000)

    # a app continua no ar após o rollback (supervisor reinicia no estado restaurado)
    for _ in range(20):
        resp = page.request.get(f"/entry/{slug}")
        if resp.ok and "App de exemplo" in resp.text():
            break
        time.sleep(1)
    else:
        raise AssertionError("app saiu do ar após rollback")

    # 7. admin desvincula o grupo do sistema
    _logout(page)
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Grupos").click()
    card = page.locator(f'[data-testid="group-card:{group_name}"]').first
    card.wait_for(timeout=30_000)
    card.get_by_role("button", name="Desvincular sistema").click()
    _select(page, "group-unlink-select", slug)
    page.locator('[data-testid=confirm-group-unlink]').click()
    card.get_by_text("sistemas: —").wait_for(timeout=30_000)
    _logout(page)
