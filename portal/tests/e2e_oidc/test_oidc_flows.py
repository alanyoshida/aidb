"""E2E do modo OIDC contra Keycloak real (change add-oidc-sso, tasks 4.4/5.x/7.3).

Usuários do realm (deploy/keycloak/aidb-realm.json, senha `e2e-senha`):
e2e-admin (admin), e2e-editor (editor), e2e-financeiro (app_user, grupo e2e-financeiro),
e2e-vendas (app_user, grupo e2e-vendas — nunca cadastrado no portal), e2e-semrole (sem papel).
"""

import uuid

import pytest

pytestmark = pytest.mark.e2e

KC_PASSWORD = "e2e-senha"
BREAKGLASS_EMAIL = "breakglass@appaiforge.local"
BREAKGLASS_PASSWORD = "bg-e2e-senha"  # definido em deploy/docker-compose.e2e-oidc.yml


def _keycloak_login(page, username: str) -> None:
    page.wait_for_url("http://localhost:8180/realms/aidb/**", timeout=30_000)
    page.locator("#username").fill(username)
    page.locator("#password").fill(KC_PASSWORD)
    page.locator("#kc-login").click()


def _sso_login(page, username: str) -> None:
    page.goto("/login")
    page.locator("[data-testid=login-sso]").click()
    _keycloak_login(page, username)
    page.locator("[data-testid=user-menu]").wait_for(timeout=30_000)


def _logout(page) -> None:
    page.goto("/auth/logout")
    page.wait_for_url("**/login*", timeout=30_000)


def _breakglass_login(page) -> None:
    page.goto("/login/local")
    page.locator("[data-testid=login-email]").fill(BREAKGLASS_EMAIL)
    page.locator("[data-testid=login-password]").fill(BREAKGLASS_PASSWORD)
    page.get_by_role("button", name="Entrar").click()
    page.locator("[data-testid=breakglass-banner]").wait_for(timeout=30_000)


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


def _select(page, testid: str, text: str) -> None:
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)
    page.locator(f"[data-testid={testid}]").click()
    menu = page.locator(".q-menu:visible")
    menu.wait_for(timeout=5_000)
    # O q-select usa rolagem virtual: com muitas opções (a suíte cheia passa de 50 sistemas) só
    # as primeiras ~30 são renderizadas. Rola o menu até a opção existir no DOM.
    option = menu.get_by_text(text, exact=True)
    for _ in range(40):
        if option.count():
            break
        menu.evaluate("m => { m.scrollTop += m.clientHeight; }")
        page.wait_for_timeout(150)
    option.click()
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)


@pytest.fixture(scope="module")
def system(browser):
    """e2e-editor cria um sistema; o break-glass cadastra o grupo `e2e-financeiro` com o
    nome do IdP e o vincula ao sistema."""
    context = browser.new_context(base_url="http://localhost:8082")
    page = context.new_page()
    slug = f"oidc-{uuid.uuid4().hex[:8]}"

    _sso_login(page, "e2e-editor")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator("[data-testid=system-name]").fill("Sistema SSO")
    page.locator("[data-testid=system-slug]").fill(slug)
    page.locator("[data-testid=create-system]").click()
    _wait_system_active(page)
    for _ in range(30):
        resp = page.request.get(f"/apps/{slug}/")
        if resp.ok and "ainda nao gerada" in resp.text():
            break
        page.wait_for_timeout(1000)
    else:
        raise AssertionError("app não ficou no ar")
    _logout(page)

    _breakglass_login(page)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Novo grupo").click()
    page.locator("[data-testid=new-group-name]").fill("e2e-financeiro")
    page.locator("[data-testid=create-group]").click()
    page.locator('[data-testid="group-card:e2e-financeiro"]').wait_for(timeout=30_000)
    page.get_by_role("button", name="Vincular a sistema").click()
    _select(page, "link-group", "e2e-financeiro")
    _select(page, "link-slug", slug)
    page.locator("[data-testid=link-system]").click()
    page.locator('[data-testid="group-card:e2e-financeiro"]').get_by_text(slug).wait_for(timeout=30_000)
    _logout(page)
    context.close()
    return slug


def test_login_sso_por_papel_sem_formulario_local(page):
    page.goto("/login")
    page.locator("[data-testid=login-sso]").wait_for(timeout=30_000)
    assert page.locator("[data-testid=login-email]").count() == 0
    page.locator("[data-testid=login-sso]").click()
    _keycloak_login(page, "e2e-editor")
    page.locator("[data-testid=user-menu]").click()
    page.get_by_text("(editor)").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Novo sistema").count() == 1


def test_admin_do_idp_ve_usuarios_somente_leitura(page):
    _sso_login(page, "e2e-admin")
    page.get_by_role("button", name="Administração").click()
    page.locator("[data-testid=users-managed-by-idp]").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Novo usuário").count() == 0
    page.locator('[data-testid="user-card:e2e-admin@e2e-oidc.local"]').wait_for(timeout=30_000)
    page.get_by_role("tab", name="Grupos").click()
    assert page.get_by_role("button", name="Adicionar membro a um grupo").count() == 0


def test_usuario_sem_papel_e_recusado(page):
    page.goto("/login")
    page.locator("[data-testid=login-sso]").click()
    _keycloak_login(page, "e2e-semrole")
    page.wait_for_url("**/login?erro=acesso_negado", timeout=30_000)
    assert "Acesso não concedido" in page.locator("[data-testid=login-error]").inner_text()


def test_link_da_app_sem_sessao_passa_pelo_keycloak_e_volta(page, system):
    page.goto(f"/apps/{system}/relatorios?mes=3")
    _keycloak_login(page, "e2e-financeiro")
    page.wait_for_url(f"http://localhost:8082/apps/{system}/relatorios?mes=3", timeout=30_000)
    assert "ainda nao gerada" in page.inner_text("body")
    # já logado: entra direto em outra página da app, sem novo login
    page.goto(f"/apps/{system}/")
    assert "ainda nao gerada" in page.inner_text("body")


def test_grupo_nao_cadastrado_nao_concede_acesso(page, system):
    _sso_login(page, "e2e-vendas")
    resp = page.goto(f"/apps/{system}/")
    assert resp.status == 403
    assert "Permissão insuficiente" in page.inner_text("body")


def test_grupo_visto_aparece_como_sugestao(page, system):
    _sso_login(page, "e2e-vendas")  # registra e2e-vendas como grupo visto
    _logout(page)
    _breakglass_login(page)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Novo grupo").click()
    page.locator('[data-testid="group-suggestion:e2e-vendas"]').wait_for(timeout=30_000)
    page.locator("[data-testid=new-group-name]").fill("nome-nunca-visto")
    page.locator("[data-testid=new-group-hint]").get_by_text("Nenhum usuário").wait_for(timeout=30_000)


def test_logout_federado_exige_credenciais_de_novo(page, system):
    _sso_login(page, "e2e-financeiro")
    _logout(page)
    assert page.locator("[data-testid=user-menu]").count() == 0
    page.goto(f"/apps/{system}/")
    # sem sessão SSO no Keycloak: o formulário de credenciais aparece de novo
    page.wait_for_url("http://localhost:8180/realms/aidb/**", timeout=30_000)
    page.locator("#username").wait_for(timeout=30_000)


def test_break_glass_entra_e_usuario_comum_nao(page):
    page.goto("/login/local")
    page.locator("[data-testid=login-email]").fill("e2e-editor@e2e-oidc.local")
    page.locator("[data-testid=login-password]").fill(KC_PASSWORD)
    page.get_by_role("button", name="Entrar").click()
    page.locator("[data-testid=login-error]").get_by_text("inválidos").wait_for(timeout=30_000)
    _breakglass_login(page)
    page.locator("[data-testid=user-menu]").wait_for(timeout=30_000)


def test_db_manager_do_idp_abre_o_catalogo(page):
    """change add-db-manager-role, task 2.5: `e2e-dba` tem `editor` e `db_manager` no token."""
    _sso_login(page, "e2e-dba")
    page.locator("[data-testid=nav-databases]").click()
    page.locator("[data-testid=new-catalog-connection]").wait_for(timeout=30_000)
    _logout(page)

    # quem só tem `editor` não vê o catálogo
    _sso_login(page, "e2e-editor")
    assert page.locator("[data-testid=nav-databases]").count() == 0
    page.goto("/databases")
    page.locator("[data-testid=databases-forbidden]").wait_for(timeout=30_000)
