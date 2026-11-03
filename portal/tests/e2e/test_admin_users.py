"""E2E browser: administração de usuários e grupos + portões de papel (task 2.3).

Usa o admin semeado pelo stack de teste (admin@appaiforge.local / admin123).
Nomes usam sufixo único por execução: o banco do stack é persistente e os
testes precisam ser idempotentes.
No NiceGUI 3.x, props data-testid caem no próprio <input> nativo.
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


def _select(page, testid: str, text: str) -> None:
    """Escolhe uma opção num ui.select do NiceGUI (menu suspenso).

    Espera o menu anterior fechar antes de abrir o próximo: evita clicar num
    dropdown ainda aberto quando há dois selects seguidos.
    """
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)
    page.locator(f"[data-testid={testid}]").click()
    page.locator(".q-menu:visible").get_by_text(text, exact=True).click()
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)


def _create_user(page, email: str, password: str, user_type: str) -> None:
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(email)
    page.locator('[data-testid=new-user-password]').fill(password)
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text(user_type, exact=True).click()
    page.locator('[data-testid=create-user]').click()


def test_admin_gerencia_usuarios_grupos_e_papéis(page, suffix):
    editor_email = f"editor-{suffix}@e2e.local"
    app_email = f"app-{suffix}@e2e.local"
    group_name = f"equipe-{suffix}"

    # admin loga e abre a administração
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()

    # cria um editor e um app_user
    _create_user(page, editor_email, "pw-editor", "editor")
    page.get_by_text(editor_email).first.wait_for(timeout=30_000)
    _create_user(page, app_email, "pw-app", "app_user")
    page.get_by_text(app_email).first.wait_for(timeout=30_000)

    # grupo + membro
    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Novo grupo").click()
    page.locator('[data-testid=new-group-name]').fill(group_name)
    page.locator('[data-testid=create-group]').click()
    page.get_by_text(f"membros: —", exact=False).first.wait_for(timeout=30_000)
    page.get_by_role("button", name="Adicionar membro a um grupo").click()
    _select(page, "member-group", group_name)
    _select(page, "member-email", app_email)
    page.locator('[data-testid=add-member]').click()
    page.get_by_text(f"membros: {app_email}").wait_for(timeout=30_000)

    _logout(page)

    # editor vê o botão de criar sistema; app_user não vê nada
    _login(page, editor_email, "pw-editor")
    page.get_by_role("button", name="Novo sistema").wait_for(timeout=30_000)
    _logout(page)

    _login(page, app_email, "pw-app")
    page.get_by_text("Nenhum sistema acessível.").wait_for(timeout=30_000)
    assert page.get_by_role("button", name="Novo sistema").count() == 0
    assert page.get_by_role("button", name="Administração").count() == 0


def test_login_invalido_mostra_mensagem_generica(page):
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill("admin@appaiforge.local")
    page.locator('[data-testid=login-password]').fill("senha-torta")
    page.get_by_role("button", name="Entrar").click()
    page.get_by_text("E-mail ou senha inválidos.").wait_for(timeout=30_000)


def _card(page, text: str):
    return page.locator(
        f'[data-testid="user-card:{text}"], [data-testid="group-card:{text}"]'
    ).first


def test_admin_edita_desativa_e_exclui_usuario(page, suffix):
    email = f"full-{suffix}@e2e.local"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()
    _create_user(page, email, "pw-full", "app_user")
    page.get_by_text(email).first.wait_for(timeout=30_000)

    # editar tipo: app_user -> editor
    _card(page, email).get_by_role("button", name="Editar tipo").click()
    page.locator('[data-testid=edit-user-type]').click()
    page.locator(".q-menu:visible").get_by_text("editor", exact=True).click()
    page.locator(".q-menu:visible").wait_for(state="hidden", timeout=5_000)
    page.locator('[data-testid=confirm-user-type]').click()
    _card(page, email).get_by_text("editor").wait_for(timeout=30_000)

    # desativar / reativar
    _card(page, email).get_by_role("button", name="Desativar").click()
    _card(page, email).get_by_text("Não").wait_for(timeout=30_000)
    _card(page, email).get_by_role("button", name="Ativar").click()
    _card(page, email).get_by_text("Sim").wait_for(timeout=30_000)

    # excluir com confirmação
    _card(page, email).get_by_role("button", name="Excluir").click()
    page.locator('[data-testid=confirm-user-delete]').click()
    page.locator(f'[data-testid="user-card:{email}"]').wait_for(state="detached", timeout=30_000)
    _logout(page)


def test_admin_gerencia_acoes_de_grupo(page, suffix):
    email = f"gm-{suffix}@e2e.local"
    group_name = f"time-{suffix}"
    renamed = f"time2-{suffix}"

    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("tab", name="Usuários").click()
    _create_user(page, email, "pw-gm", "app_user")
    page.get_by_text(email).first.wait_for(timeout=30_000)

    page.get_by_role("tab", name="Grupos").click()
    page.get_by_role("button", name="Novo grupo").click()
    page.locator('[data-testid=new-group-name]').fill(group_name)
    page.locator('[data-testid=create-group]').click()
    _card(page, group_name).wait_for(timeout=30_000)

    # adiciona e depois remove um membro
    page.get_by_role("button", name="Adicionar membro a um grupo").click()
    _select(page, "member-group", group_name)
    _select(page, "member-email", email)
    page.locator('[data-testid=add-member]').click()
    page.get_by_text(f"membros: {email}").wait_for(timeout=30_000)

    # renomeia
    _card(page, group_name).get_by_role("button", name="Renomear").click()
    page.locator('[data-testid=group-rename-name]').fill(renamed)
    page.locator('[data-testid=confirm-group-rename-name]').click()
    _card(page, renamed).wait_for(timeout=30_000)

    # remove membro
    _card(page, renamed).get_by_role("button", name="Remover membro").click()
    _select(page, "group-remove-member-select", email)
    page.locator('[data-testid=confirm-group-remove-member]').click()
    _card(page, renamed).get_by_text("membros: —").wait_for(timeout=30_000)

    # exclui o grupo (com confirmação)
    _card(page, renamed).get_by_role("button", name="Excluir").click()
    page.locator('[data-testid=confirm-group-delete]').click()
    page.locator(f'[data-testid="group-card:{renamed}"]').wait_for(state="detached", timeout=30_000)

    # a ação aparece na trilha de auditoria de gestão (task 8.1)
    page.get_by_role("tab", name="Auditoria de gestão").click()
    page.get_by_text("group.delete").first.wait_for(timeout=30_000)
    _logout(page)
