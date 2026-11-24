"""Passos de navegador do catálogo de conexões (change add-db-manager-role), compartilhados pelos
testes E2E: cadastrar no catálogo, autorizar para um sistema e ativar no sistema.

O alvo das conexões é o próprio Postgres/MySQL do stack (hosts "postgres" e "mysql" na rede
interna). Nomes no catálogo são únicos na instalação inteira e o banco do stack é persistente,
então cada teste usa um sufixo próprio."""

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"


def login(page, email: str, password: str) -> None:
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill(email)
    page.locator('[data-testid=login-password]').fill(password)
    page.get_by_role("button", name="Entrar").click()
    page.locator('[data-testid=user-menu]').wait_for(timeout=30_000)


def logout(page) -> None:
    page.locator('[data-testid=user-menu]').click()
    page.locator('[data-testid=logout]').click()
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def pick(page, testid: str, text: str, scope=None) -> None:
    """Escolhe uma opção de um ui.select pelo texto (contém)."""
    root = scope if scope is not None else page
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)
    root.locator(f"[data-testid={testid}]").click()
    menu = page.locator(".q-menu:visible")
    menu.wait_for(timeout=5_000)
    menu.get_by_text(text).first.click()
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)


def create_user(page, email: str, password: str, user_type: str, db_manager: bool = False) -> None:
    """Admin já logado cria um usuário (modo local)."""
    page.goto("/admin")
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill(password)
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text(user_type, exact=True).click()
    if db_manager:
        page.locator('[data-testid=new-user-db-manager]').click()
    page.locator('[data-testid=create-user]').click()
    page.locator(f'[data-testid="user-card:{email}"]').wait_for(timeout=30_000)


def create_system(page, name: str, slug: str) -> None:
    page.goto("/")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill(name)
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_role("tab", name="Chat").wait_for(timeout=30_000)


def open_catalog(page) -> None:
    page.goto("/databases")
    page.locator('[data-testid=new-catalog-connection]').wait_for(timeout=30_000)


def fill_catalog_connection(page, name: str, database: str, password: str, host: str = "postgres",
                            port: str = "5432", kind: str = "PostgreSQL", user: str = "appaiforge",
                            description: str | None = None) -> None:
    """Abre "Nova conexão" no catálogo, preenche e clica em "Testar e salvar"."""
    field = page.locator('[data-testid=conn-name]')
    if field.is_visible():
        try:
            page.get_by_role("button", name="Cancelar").click(timeout=3_000)
        except Exception:
            pass
    field.wait_for(state="hidden", timeout=30_000)
    page.locator('[data-testid=new-catalog-connection]').click()
    field.wait_for(state="visible", timeout=30_000)
    if kind != "PostgreSQL":
        pick(page, "conn-kind", kind)
    field.fill(name)
    if kind == "BigQuery":
        page.locator('[data-testid=conn-bq-project]').fill(host)
        page.locator('[data-testid=conn-bq-dataset]').fill(database)
        page.locator('[data-testid=conn-bq-sa-json]').fill(password)
    else:
        page.locator('[data-testid=conn-host]').fill(host)
        page.locator('[data-testid=conn-port]').fill(port)
        page.locator('[data-testid=conn-database]').fill(database)
        page.locator('[data-testid=conn-user]').fill(user)
        page.locator('[data-testid=conn-password]').fill(password)
    if description:
        page.locator('[data-testid=conn-description]').fill(description)
    page.locator('[data-testid=save-connection]').click()


def create_catalog_connection(page, name: str, database: str = "appaiforge", password: str = "appaiforge",
                              **kw) -> None:
    open_catalog(page)
    fill_catalog_connection(page, name, database, password, **kw)
    catalog_card(page, name).wait_for(timeout=30_000)


def catalog_card(page, name: str):
    return page.locator(f'[data-testid="catalog-conn:{name}"]')


def open_grants(page, name: str):
    card = catalog_card(page, name)
    card.wait_for(timeout=30_000)
    header = card.locator(".q-expansion-item__container > .q-item").first
    if header.get_attribute("aria-expanded") != "true":
        header.click()
    card.locator('[data-testid=grant-submit]').wait_for(timeout=10_000)
    return card


def grant(page, conn_name: str, slug: str, ceiling: str | None = None) -> None:
    """No catálogo, autoriza a conexão para o sistema pelo slug (teto opcional, pelo rótulo)."""
    card = open_grants(page, conn_name)
    pick(page, "grant-system", f"({slug})", scope=card)
    if ceiling:
        pick(page, "grant-ceiling-new", ceiling, scope=card)
    card.locator('[data-testid=grant-submit]').click()
    card.locator(f'[data-testid="grant-row:{slug}"]').wait_for(timeout=30_000)


def open_system_connections(page, slug: str) -> None:
    page.goto("/")
    page.get_by_text(f"/{slug}", exact=True).first.click()
    page.get_by_role("tab", name="Conexões").click()


def activate(page, conn_name: str, alias: str, mode: str | None = None) -> None:
    """Na aba Conexões do sistema, ativa a conexão autorizada com alias e modo (rótulo)."""
    card = page.locator(f'[data-testid="conn-card:{conn_name}"]')
    card.locator('[data-testid=conn-activate]').click()
    alias_field = page.locator('[data-testid=activate-alias]')
    alias_field.wait_for(state="visible", timeout=10_000)
    alias_field.fill(alias)
    if mode:
        pick(page, "activate-mode", mode)
    page.locator('[data-testid=confirm-activate]').click()
    card.locator('[data-testid=conn-mode-badge]').wait_for(timeout=30_000)
