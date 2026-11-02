"""Administração de usuários e grupos (somente admin; spec portal-identity)."""

from nicegui import ui
from sqlalchemy import select

from ..db import session_scope
from ..models import User
from ..services import directory
from .common import get_current_user, render_header


def register() -> None:
    @ui.page("/admin")
    def admin_page() -> None:
        user = get_current_user()
        if user is None:
            ui.navigate.to("/login")
            return
        if not user.is_admin:
            render_header(user)
            ui.label("Permissão insuficiente.").classes("text-red-600 text-lg m-8")
            return

        render_header(user)
        ui.label("Administração").classes("text-2xl font-bold m-4")
        with ui.tabs().classes("w-full") as tabs:
            usuarios_tab = ui.tab("Usuários")
            grupos_tab = ui.tab("Grupos")
        with ui.tab_panels(tabs, value=usuarios_tab).classes("w-full"):
            with ui.tab_panel(usuarios_tab):
                _users_panel()
            with ui.tab_panel(grupos_tab):
                _groups_panel()


def _users_panel() -> None:
    table = ui.table(rows=[], columns=[
        {"name": "email", "label": "E-mail", "field": "email"},
        {"name": "type", "label": "Tipo", "field": "type"},
        {"name": "active", "label": "Ativo", "field": "active"},
    ], row_key="email").classes("w-full")

    def refresh() -> None:
        table.rows = [{"email": e, "type": t, "active": str(a)} for e, t, a in directory.list_users()]
        table.update()

    with ui.card().classes("w-full"):
        ui.label("Novo usuário").classes("font-semibold")
        email = ui.input("E-mail").props("data-testid=new-user-email")
        password = ui.input("Senha", password=True).props("data-testid=new-user-password")
        utype = ui.select(["admin", "editor", "app_user"], value="app_user", label="Tipo").props("data-testid=new-user-type")
        feedback = ui.label("").classes("text-sm")

        def create() -> None:
            try:
                directory.create_user_as_admin(email.value, password.value, utype.value)
                feedback.classes("text-green-600 text-sm").set_text(f"usuário {email.value} criado")
                email.set_value("")
                password.set_value("")
                refresh()
            except Exception as exc:
                feedback.classes("text-red-600 text-sm").set_text(f"falha: {exc}")

        ui.button("Criar usuário", on_click=create).props("data-testid=create-user")
    refresh()


def _groups_panel() -> None:
    listing = ui.column().classes("w-full")

    def refresh() -> None:
        listing.clear()
        with listing:
            for name, emails, slugs in directory.list_groups():
                with ui.card().classes("w-full"):
                    ui.label(name).classes("font-semibold")
                    ui.label(f"membros: {', '.join(emails) or '—'}").classes("text-sm text-gray-600")
                    ui.label(f"sistemas: {', '.join(slugs) or '—'}").classes("text-sm text-gray-600")

    with ui.card().classes("w-full"):
        ui.label("Novo grupo").classes("font-semibold")
        gname = ui.input("Nome do grupo").props("data-testid=new-group-name")

        def create_group_action() -> None:
            try:
                directory.create_group(gname.value)
                gname.set_value("")
                refresh()
            except Exception as exc:
                ui.notify(f"falha ao criar grupo: {exc}", type="negative")

        ui.button("Criar grupo", on_click=create_group_action).props("data-testid=create-group")

    with ui.card().classes("w-full"):
        ui.label("Adicionar membro").classes("font-semibold")
        m_group = ui.input("Grupo").props("data-testid=member-group")
        m_email = ui.input("E-mail do usuário").props("data-testid=member-email")

        def add_member_action() -> None:
            directory.add_member(m_group.value, m_email.value)
            m_group.set_value("")
            m_email.set_value("")
            refresh()

        ui.button("Adicionar", on_click=add_member_action).props("data-testid=add-member")

    with ui.card().classes("w-full"):
        ui.label("Vincular grupo a sistema").classes("font-semibold")
        l_group = ui.input("Grupo").props("data-testid=link-group")
        l_slug = ui.input("Slug do sistema").props("data-testid=link-slug")

        def link_action() -> None:
            directory.link_group_to_system(l_group.value, l_slug.value)
            l_group.set_value("")
            l_slug.set_value("")
            refresh()

        ui.button("Vincular", on_click=link_action).props("data-testid=link-system")
    refresh()
