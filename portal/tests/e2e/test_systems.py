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
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill("pw-editor")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(email).first.wait_for(timeout=30_000)
    _logout(page)


def _fill_connection(page, name: str, database: str, password: str) -> None:
    # a nova conexão abre em diálogo; uma tentativa inválida deixa o diálogo
    # aberto com o feedback, então fecha antes de (re)abrir com estado limpo
    field = page.locator('[data-testid=conn-name]')
    if field.is_visible():
        try:
            page.get_by_role("button", name="Cancelar").click(timeout=3_000)
        except Exception:
            pass
    field.wait_for(state="hidden", timeout=30_000)
    page.get_by_role("button", name="Nova conexão").click()
    field.wait_for(state="visible", timeout=30_000)
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

    # renomeia o sistema e confere no cabeçalho (ações ficam na aba Configurações)
    page.get_by_role("tab", name="Chat").wait_for(timeout=30_000)
    page.get_by_role("tab", name="Configurações").click()
    page.locator('[data-testid=rename-system]').click()
    page.locator('[data-testid=rename-system-name]').fill("Sistema E2E Renomeado")
    page.locator('[data-testid=confirm-rename-system]').click()
    page.get_by_text("Sistema E2E Renomeado").first.wait_for(timeout=30_000)

    # troca provedor/modelo e confere no cabeçalho
    page.locator('[data-testid=edit-provider]').click()
    page.locator('[data-testid=edit-provider-select]').click()
    page.locator('.q-menu:visible').get_by_text("anthropic", exact=True).click()
    page.locator('.q-menu:visible').wait_for(state="hidden", timeout=5_000)
    page.locator('[data-testid=edit-model-select]').click()
    page.locator('.q-menu:visible').get_by_text("claude-3-5-sonnet-latest", exact=True).click()
    page.locator('.q-menu:visible').wait_for(state="hidden", timeout=5_000)
    page.locator('[data-testid=confirm-provider]').click()
    page.get_by_text("provedor: anthropic").wait_for(timeout=30_000)

    # detalhe do sistema carrega; conexões ficam na própria aba
    page.get_by_role("tab", name="Conexões").click()

    # conexão inválida é recusada com feedback
    _fill_connection(page, "errada", "appaiforge", "senha-torta")
    page.get_by_text("teste de conexão falhou").wait_for(timeout=30_000)

    # duas conexões válidas a bancos distintos são aceitas
    _fill_connection(page, "vendas", "appaiforge", "appaiforge")
    page.get_by_text("conexão cadastrada").wait_for(timeout=20_000)
    page.get_by_text("appaiforge@postgres:5432/appaiforge").wait_for(timeout=30_000)

    _fill_connection(page, "fiscal", "appaiforge2", "appaiforge")
    page.get_by_text("appaiforge@postgres:5432/appaiforge2").wait_for(timeout=30_000)

    # edita os metadados da conexão 'vendas'
    page.locator('[data-testid="conn-card:vendas"]').get_by_role("button", name="Editar").click()
    page.locator('[data-testid=edit-conn-name]').fill("vendas-editada")
    page.locator('[data-testid=save-connection-edit]').click()
    page.get_by_text("vendas-editada").first.wait_for(timeout=30_000)

    # remove a conexão 'fiscal' com confirmação
    page.locator('[data-testid="conn-card:fiscal"]').get_by_role("button", name="Remover").click()
    page.locator('[data-testid=confirm-remove-connection]').click()
    page.locator('[data-testid="conn-card:fiscal"]').wait_for(state="detached", timeout=30_000)

    # nenhuma senha aparece na tela
    content = page.content()
    assert "senha-torta" not in content

    # o novo nome reflete na lista de sistemas
    page.goto("/")
    page.get_by_text("Sistema E2E Renomeado").first.wait_for(timeout=30_000)


def test_slug_duplicado_mostra_feedback(page, suffix):
    editor_email = f"slug-editor-{suffix}@e2e.local"
    slug = f"dupsys-{suffix}"
    _create_editor_via_admin(page, editor_email)

    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Primeiro")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_role("tab", name="Chat").wait_for(timeout=30_000)

    page.goto("/systems/new")
    page.locator('[data-testid=system-name]').fill("Segundo")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_text("já existe").wait_for(timeout=30_000)


def test_provedor_custom_disponivel_na_criacao(page, suffix):
    provider = f"prov-{suffix}"

    # admin cadastra um provedor custom no catálogo
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Provedores de LLM").click()
    page.locator('[data-testid=provider-new]').click()
    page.locator('[data-testid=provider-id]').fill(provider)
    page.locator('[data-testid=provider-label]').fill("Provedor Custom")
    page.locator('[data-testid=provider-base-url]').fill("http://127.0.0.1:9/v1")
    page.locator('[data-testid=confirm-provider-create]').click()
    page.locator(f'[data-testid="key-card:{provider}"]').wait_for(timeout=30_000)
    _logout(page)

    # o editor vê o provedor do catálogo no select de criação de sistema
    editor_email = f"cat-editor-{suffix}@e2e.local"
    _create_editor_via_admin(page, editor_email)
    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-provider]').click()
    page.locator(".q-menu:visible").get_by_text(provider, exact=True).wait_for(timeout=30_000)
    _logout(page)
