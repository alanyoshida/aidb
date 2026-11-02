"""Administração de usuários e grupos (somente admin; spec portal-identity)."""

from nicegui import ui
from sqlalchemy import select

from ..db import session_scope
from ..models import System, User
from ..services import directory
from .common import get_current_user, render_header


def _system_slugs() -> list[str]:
    with session_scope() as s:
        return list(s.execute(select(System.slug).order_by(System.slug)).scalars().all())


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
            usuarios_tab = ui.tab("Usuários", icon="people")
            grupos_tab = ui.tab("Grupos", icon="group")
        with ui.tab_panels(tabs, value=usuarios_tab).classes("w-full"):
            with ui.tab_panel(usuarios_tab):
                _users_panel()
            with ui.tab_panel(grupos_tab):
                _groups_panel()


def _users_panel() -> None:
    def refresh() -> None:
        table.rows = [{"email": e, "type": t, "active": "Sim" if a else "Não"} for e, t, a in directory.list_users()]
        table.update()

    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("Novo usuário").classes("font-semibold text-lg")
        email = ui.input("E-mail").classes("w-full").props("data-testid=new-user-email")
        password = ui.input("Senha", password=True).classes("w-full").props("data-testid=new-user-password")
        utype = ui.select(["admin", "editor", "app_user"], value="app_user", label="Tipo").classes("w-full").props("data-testid=new-user-type")
        feedback = ui.label("").classes("text-sm")

        def create() -> None:
            try:
                directory.create_user_as_admin(email.value, password.value, utype.value)
                feedback.classes(remove="text-red-600", add="text-green-600").set_text("")
                refresh()
                dialog.close()
            except Exception as exc:
                feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"falha: {exc}")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=dialog.close).props("flat")
            ui.button("Criar usuário", icon="person_add", on_click=create).props("data-testid=create-user")

    def open_create_dialog() -> None:
        # limpar ao ABRIR (não ao fechar): um set_value logo antes de
        # dialog.close() pode não chegar ao cliente antes do dialog sumir,
        # deixando o valor antigo no campo na próxima abertura
        email.set_value("")
        password.set_value("")
        utype.set_value("app_user")
        feedback.set_text("")
        dialog.open()

    ui.button("Novo usuário", icon="add", on_click=open_create_dialog).classes("mb-3")
    table = ui.table(rows=[], columns=[
        {"name": "email", "label": "E-mail", "field": "email"},
        {"name": "type", "label": "Tipo", "field": "type"},
        {"name": "active", "label": "Ativo", "field": "active"},
    ], row_key="email").classes("w-full")
    refresh()


def _groups_panel() -> None:
    def refresh() -> None:
        listing.clear()
        groups = directory.list_groups()
        with listing:
            if not groups:
                ui.label("Nenhum grupo ainda.").classes("text-gray-500 text-sm")
                return
            for name, emails, slugs in groups:
                with ui.card().classes("w-full"):
                    ui.label(name).classes("font-semibold")
                    ui.label(f"membros: {', '.join(emails) or '—'}").classes("text-sm text-gray-600")
                    ui.label(f"sistemas: {', '.join(slugs) or '—'}").classes("text-sm text-gray-600")

    with ui.dialog() as group_dialog, ui.card().classes("w-96"):
        ui.label("Novo grupo").classes("font-semibold text-lg")
        gname = ui.input("Nome do grupo").classes("w-full").props("data-testid=new-group-name")

        def create_group_action() -> None:
            try:
                directory.create_group(gname.value)
                refresh()
                group_dialog.close()
            except Exception as exc:
                ui.notify(f"falha ao criar grupo: {exc}", type="negative")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=group_dialog.close).props("flat")
            ui.button("Criar grupo", icon="add", on_click=create_group_action).props("data-testid=create-group")

    def open_group_dialog() -> None:
        gname.set_value("")
        group_dialog.open()

    with ui.dialog() as member_dialog, ui.card().classes("w-96"):
        ui.label("Adicionar membro a um grupo").classes("font-semibold text-lg")
        m_group = ui.select([], label="Grupo").classes("w-full").props("data-testid=member-group")
        m_email = ui.select([], label="Usuário").classes("w-full").props("data-testid=member-email")

        def add_member_action() -> None:
            directory.add_member(m_group.value, m_email.value)
            refresh()
            member_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=member_dialog.close).props("flat")
            ui.button("Adicionar ao grupo", icon="person_add", on_click=add_member_action).props("data-testid=add-member")

    def open_member_dialog() -> None:
        group_names = [name for name, _, _ in directory.list_groups()]
        user_emails = [email for email, _, _ in directory.list_users()]
        m_group.set_options(group_names, value=None)
        m_email.set_options(user_emails, value=None)
        member_dialog.open()

    with ui.dialog() as link_dialog, ui.card().classes("w-96"):
        ui.label("Vincular grupo a sistema").classes("font-semibold text-lg")
        l_group = ui.select([], label="Grupo").classes("w-full").props("data-testid=link-group")
        l_slug = ui.select([], label="Sistema").classes("w-full").props("data-testid=link-slug")

        def link_action() -> None:
            directory.link_group_to_system(l_group.value, l_slug.value)
            refresh()
            link_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=link_dialog.close).props("flat")
            ui.button("Vincular ao sistema", icon="link", on_click=link_action).props("data-testid=link-system")

    def open_link_dialog() -> None:
        group_names = [name for name, _, _ in directory.list_groups()]
        l_group.set_options(group_names, value=None)
        l_slug.set_options(_system_slugs(), value=None)
        link_dialog.open()

    with ui.row().classes("mb-3 gap-2"):
        ui.button("Novo grupo", icon="add", on_click=open_group_dialog)
        ui.button("Adicionar membro a um grupo", icon="person_add", on_click=open_member_dialog)
        ui.button("Vincular a sistema", icon="link", on_click=open_link_dialog)

    listing = ui.column().classes("w-full")
    refresh()
