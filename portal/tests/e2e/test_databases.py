"""E2E browser: catálogo de conexões, autorizações e ativação pelo dono (change
add-db-manager-role, tasks 7.1 a 7.4). Usa o admin semeado pelo stack de teste."""

import uuid

import pytest
from catalog_flow import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    activate,
    catalog_card,
    create_catalog_connection,
    create_system,
    create_user,
    fill_catalog_connection,
    grant,
    login,
    logout,
    open_catalog,
    open_grants,
    open_system_connections,
    pick,
)

pytestmark = pytest.mark.e2e

_FAKE_SA_JSON = """{
  "type": "service_account",
  "project_id": "bq-test",
  "private_key_id": "key123",
  "client_email": "sa@bq-test.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}"""


@pytest.fixture()
def suffix() -> str:
    return uuid.uuid4().hex[:8]


def test_db_manager_gere_o_catalogo_e_editor_nao_ve(page, suffix):
    """7.1: um DB Manager cadastra (Postgres, MySQL e BigQuery) e edita; quem não tem a
    capacidade não vê o item de menu e tem o acesso direto recusado."""
    dba, editor = f"dba-{suffix}@e2e.local", f"ed-{suffix}@e2e.local"
    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    create_user(page, dba, "pw-dba", "editor", db_manager=True)
    create_user(page, editor, "pw-ed", "editor")
    logout(page)

    login(page, dba, "pw-dba")
    page.locator('[data-testid=nav-databases]').click()
    page.locator('[data-testid=new-catalog-connection]').wait_for(timeout=30_000)

    # credencial errada é recusada com o motivo, sem vazar a senha
    fill_catalog_connection(page, f"errada-{suffix}", "appaiforge", "senha-torta")
    page.get_by_text("teste de conexão falhou").wait_for(timeout=30_000)
    page.get_by_role("button", name="Cancelar").click()

    name = f"vendas-{suffix}"
    create_catalog_connection(page, name, description="Pedidos")
    card = catalog_card(page, name)
    card.get_by_text("appaiforge@postgres:5432/appaiforge").wait_for(timeout=10_000)

    # edição: renomeia sem mexer na credencial
    card.locator('[data-testid=catalog-conn-edit]').click()
    page.locator('[data-testid=conn-name]').fill(f"{name}-editada")
    page.locator('[data-testid=save-connection]').click()
    catalog_card(page, f"{name}-editada").wait_for(timeout=30_000)

    create_catalog_connection(page, f"mysql-{suffix}", host="mysql", port="3306", kind="MySQL")
    create_catalog_connection(page, f"bq-{suffix}", "e2e", _FAKE_SA_JSON, host="bq-test", kind="BigQuery")
    catalog_card(page, f"bq-{suffix}").get_by_text("sa@bq-test.iam.gserviceaccount.com", exact=False).wait_for(
        timeout=10_000
    )
    assert "senha-torta" not in page.content()
    logout(page)

    login(page, editor, "pw-ed")
    assert page.locator('[data-testid=nav-databases]').count() == 0
    page.goto("/databases")
    page.locator('[data-testid=databases-forbidden]').wait_for(timeout=30_000)
    assert page.locator('[data-testid=new-catalog-connection]').count() == 0


def test_autorizar_elevar_teto_e_revogar(page, suffix):
    """7.2: autorizar para dois sistemas, elevar o teto com confirmação de conexão
    compartilhada (cancelar volta o seletor), e revogar com confirmação."""
    x, y = f"cat-x-{suffix}", f"cat-y-{suffix}"
    name = f"compartilhada-{suffix}"
    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    create_system(page, "Catálogo X", x)
    create_system(page, "Catálogo Y", y)
    create_catalog_connection(page, name)
    grant(page, name, x)
    grant(page, name, y)

    card = open_grants(page, name)
    row_x = card.locator(f'[data-testid="grant-row:{x}"]')
    # cancelar a confirmação não aplica o teto e o seletor volta ao valor real
    pick(page, "grant-ceiling", "Leitura, escrita e DDL", scope=row_x)
    page.get_by_text("Liberar DDL numa conexão compartilhada").wait_for(timeout=10_000)
    page.get_by_text(f"({y})").last.wait_for(timeout=5_000)
    page.locator('[data-testid=cancel-action]').click()
    card = open_grants(page, name)
    row_x = card.locator(f'[data-testid="grant-row:{x}"]')
    row_x.get_by_text("Leitura e escrita", exact=True).wait_for(timeout=10_000)

    # confirmando, o teto passa a valer
    pick(page, "grant-ceiling", "Leitura, escrita e DDL", scope=row_x)
    page.locator('[data-testid=confirm-action]').click()
    card = open_grants(page, name)
    card.locator(f'[data-testid="grant-row:{x}"]').get_by_text("Leitura, escrita e DDL", exact=True).wait_for(
        timeout=10_000
    )

    # revogar com confirmação
    card.locator(f'[data-testid="grant-row:{y}"]').locator('[data-testid=grant-revoke]').click()
    page.locator('[data-testid=confirm-action]').click()
    card = open_grants(page, name)
    card.locator(f'[data-testid="grant-row:{y}"]').wait_for(state="detached", timeout=30_000)


def test_conexoes_degradadas_na_pagina_nova(page, suffix):
    """7.3: o resumo de degradadas mora em "Bancos de dados", não mais na administração."""
    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    open_catalog(page)
    page.get_by_role("tab", name="Conexões degradadas").click()
    page.locator('[data-testid=degraded-connections-box]').wait_for(timeout=30_000)
    page.goto("/admin")
    page.get_by_role("tab", name="Usuários").wait_for(timeout=30_000)
    assert page.get_by_role("tab", name="Conexões degradadas").count() == 0


def test_dono_ativa_com_alias_e_dispensa_aviso_de_revogacao(page, suffix):
    """7.4: o dono só vê nome, descrição, tipo e saúde; ativa com alias próprio; recebe aviso
    quando o DB Manager revoga, e o dispensa."""
    owner, slug, name = f"dono-{suffix}@e2e.local", f"dono-sys-{suffix}", f"vendas-dono-{suffix}"
    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    create_user(page, owner, "pw-dono", "editor")
    logout(page)

    login(page, owner, "pw-dono")
    create_system(page, "Sistema do Dono", slug)
    page.get_by_role("tab", name="Conexões").click()
    page.locator('[data-testid=conn-empty]').wait_for(timeout=30_000)
    logout(page)

    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    create_catalog_connection(page, name, description="Pedidos e clientes")
    grant(page, name, slug)
    logout(page)

    login(page, owner, "pw-dono")
    open_system_connections(page, slug)
    activate(page, name, "vendas", "Somente leitura")
    card = page.locator(f'[data-testid="conn-card:{name}"]')
    card.get_by_text("DATABASE_URL_VENDAS", exact=False).wait_for(timeout=10_000)
    card.get_by_text("Somente leitura", exact=True).wait_for(timeout=10_000)
    content = page.content()
    assert "postgres:5432" not in content and "appaiforge@postgres" not in content
    logout(page)

    login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    open_catalog(page)
    card = open_grants(page, name)
    card.locator(f'[data-testid="grant-row:{slug}"]').locator('[data-testid=grant-revoke]').click()
    page.locator('[data-testid=confirm-action]').click()
    open_grants(page, name).locator(f'[data-testid="grant-row:{slug}"]').wait_for(state="detached", timeout=30_000)
    logout(page)

    login(page, owner, "pw-dono")
    open_system_connections(page, slug)
    notice = page.locator('[data-testid="conn-notice:revoked"]')
    notice.get_by_text("A conexão vendas foi revogada", exact=False).wait_for(timeout=30_000)
    notice.locator('[data-testid=conn-notice-dismiss]').click()
    notice.wait_for(state="detached", timeout=30_000)
    page.locator('[data-testid=conn-empty]').wait_for(timeout=10_000)
