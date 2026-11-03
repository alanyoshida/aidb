"""Administração de usuários, grupos, chaves de LLM e auditoria (specs portal-identity, llm-provider-keys, management-audit)."""

from nicegui import ui
from sqlalchemy import select

from ..db import session_scope
from ..models import System, User
from ..services import audit, catalog, directory, provider_keys
from .common import get_current_user, render_header

_USER_TYPES = ["admin", "editor", "app_user"]


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
            keys_tab = ui.tab("Provedores de LLM", icon="vpn_key")
            audit_tab = ui.tab("Auditoria de gestão", icon="history")
        with ui.tab_panels(tabs, value=usuarios_tab).classes("w-full"):
            with ui.tab_panel(usuarios_tab):
                _users_panel(user)
            with ui.tab_panel(grupos_tab):
                _groups_panel(user)
            with ui.tab_panel(keys_tab):
                _llm_keys_panel(user)
            with ui.tab_panel(audit_tab):
                _audit_panel()


def _users_panel(user: User) -> None:
    def refresh() -> None:
        users_box.clear()
        with users_box:
            for email, utype, active in directory.list_users():
                with ui.card().classes("w-full").props(f"data-testid=user-card:{email}"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("person").classes("text-gray-500")
                        ui.label(email).classes("font-semibold")
                        ui.label(utype).classes("text-xs text-gray-500")
                        ui.badge("Sim" if active else "Não").props(
                            "color=positive" if active else "color=grey"
                        )
                    with ui.row().classes("gap-2"):
                        ui.button("Editar tipo", icon="badge", on_click=lambda e=email, t=utype: open_type_dialog(e, t)).props("dense outline data-testid=user-edit-type")
                        ui.button("Desativar" if active else "Ativar", icon="toggle_off" if active else "toggle_on", on_click=lambda e=email, a=active: toggle_active(e, a)).props("dense outline data-testid=user-toggle-active")
                        ui.button("Excluir", icon="delete", on_click=lambda e=email: ask_delete(e)).props("dense outline color=negative data-testid=user-delete")

    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("Novo usuário").classes("font-semibold text-lg")
        email = ui.input("E-mail").classes("w-full").props("data-testid=new-user-email")
        password = ui.input("Senha", password=True).classes("w-full").props("data-testid=new-user-password")
        utype = ui.select(_USER_TYPES, value="app_user", label="Tipo").classes("w-full").props("data-testid=new-user-type")
        feedback = ui.label("").classes("text-sm")

        def create() -> None:
            try:
                directory.create_user_as_admin(email.value, password.value, utype.value, actor=user)
            except Exception as exc:
                feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"falha: {exc}")
                return
            feedback.classes(remove="text-red-600", add="text-green-600").set_text("")
            refresh()
            dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=dialog.close).props("flat")
            ui.button("Criar usuário", icon="person_add", on_click=create).props("data-testid=create-user")

    def open_create_dialog() -> None:
        email.set_value("")
        password.set_value("")
        utype.set_value("app_user")
        feedback.set_text("")
        dialog.open()

    edit_target: dict = {"email": None}

    with ui.dialog() as type_dialog, ui.card().classes("w-96"):
        ui.label("Editar tipo de usuário").classes("font-semibold text-lg")
        type_select = ui.select(_USER_TYPES, label="Tipo").classes("w-full").props("data-testid=edit-user-type")

        def save_type() -> None:
            directory.update_user_type(edit_target["email"], type_select.value, user)
            refresh()
            type_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=type_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=save_type).props("data-testid=confirm-user-type")

    def open_type_dialog(target_email: str, current_type: str) -> None:
        edit_target["email"] = target_email
        type_select.set_options(_USER_TYPES, value=current_type)
        type_dialog.open()

    def toggle_active(target_email: str, active: bool) -> None:
        directory.set_user_active(target_email, not active, actor=user)
        refresh()

    delete_target: dict = {"email": None}

    with ui.dialog() as delete_dialog, ui.card().classes("w-96"):
        ui.label("Excluir usuário").classes("font-semibold text-lg")
        delete_message = ui.label("").classes("text-sm text-gray-600")

        def confirm_delete() -> None:
            directory.delete_user(delete_target["email"], user)
            delete_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=delete_dialog.close).props("flat")
            ui.button("Excluir", icon="delete", on_click=confirm_delete).props("color=negative data-testid=confirm-user-delete")

    def ask_delete(target_email: str) -> None:
        delete_target["email"] = target_email
        count = directory.owned_system_count(target_email)
        extra = f" {count} sistema(s) dele serão transferidos para você." if count else ""
        delete_message.set_text(f"Excluir o usuário '{target_email}'?{extra}")
        delete_dialog.open()

    ui.button("Novo usuário", icon="add", on_click=open_create_dialog).classes("mb-3")
    users_box = ui.column().classes("w-full max-w-3xl gap-2")
    refresh()


def _groups_panel(user: User) -> None:
    def refresh() -> None:
        listing.clear()
        groups = directory.list_groups()
        with listing:
            if not groups:
                ui.label("Nenhum grupo ainda.").classes("text-gray-500 text-sm")
                return
            for name, emails, slugs in groups:
                with ui.card().classes("w-full").props(f"data-testid=group-card:{name}"):
                    ui.label(name).classes("font-semibold")
                    ui.label(f"membros: {', '.join(emails) or '—'}").classes("text-sm text-gray-600")
                    ui.label(f"sistemas: {', '.join(slugs) or '—'}").classes("text-sm text-gray-600")
                    with ui.row().classes("gap-2"):
                        ui.button("Renomear", icon="edit", on_click=lambda n=name: open_rename(n)).props("dense outline data-testid=group-rename")
                        ui.button("Remover membro", icon="person_remove", on_click=lambda n=name, e=emails: open_remove_member(n, e)).props("dense outline data-testid=group-remove-member")
                        ui.button("Desvincular sistema", icon="link_off", on_click=lambda n=name, s=slugs: open_unlink(n, s)).props("dense outline data-testid=group-unlink")
                        ui.button("Excluir", icon="delete", on_click=lambda n=name: open_delete(n)).props("dense outline color=negative data-testid=group-delete")

    def _simple_dialog(action, testid, label, icon):
        with ui.dialog() as dlg, ui.card().classes("w-96"):
            ui.label(label).classes("font-semibold text-lg")
            field = ui.input().classes("w-full").props(f"data-testid={testid}")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=dlg.close).props("flat")
                ui.button("Salvar", icon="save", on_click=lambda: action(field.value, dlg)).props("data-testid=confirm-" + testid)
        return dlg, field

    with ui.dialog() as group_dialog, ui.card().classes("w-96"):
        ui.label("Novo grupo").classes("font-semibold text-lg")
        gname = ui.input("Nome do grupo").classes("w-full").props("data-testid=new-group-name")

        def create_group_action() -> None:
            try:
                directory.create_group(gname.value, actor=user)
            except Exception as exc:
                ui.notify(f"falha ao criar grupo: {exc}", type="negative")
                return
            refresh()
            group_dialog.close()

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
            directory.add_member(m_group.value, m_email.value, actor=user)
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
            directory.link_group_to_system(l_group.value, l_slug.value, actor=user)
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

    rename_dialog, rename_input = _simple_dialog(
        lambda value, dlg: (directory.rename_group(group_target["name"], value, user), dlg.close(), refresh()),
        "group-rename-name", "Renomear grupo", "edit",
    )
    group_target: dict = {"name": None}

    def open_rename(name: str) -> None:
        group_target["name"] = name
        rename_input.set_value(name)
        rename_dialog.open()

    with ui.dialog() as rmember_dialog, ui.card().classes("w-96"):
        ui.label("Remover membro").classes("font-semibold text-lg")
        rmember_select = ui.select([], label="Membro").classes("w-full").props("data-testid=group-remove-member-select")
        rmember_target: dict = {"name": None}

        def confirm_remove_member() -> None:
            directory.remove_member(rmember_target["name"], rmember_select.value, user)
            rmember_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=rmember_dialog.close).props("flat")
            ui.button("Remover", icon="person_remove", on_click=confirm_remove_member).props("data-testid=confirm-group-remove-member")

    def open_remove_member(name: str, emails: list[str]) -> None:
        rmember_target["name"] = name
        rmember_select.set_options(emails, value=None)
        rmember_dialog.open()

    with ui.dialog() as unlink_dialog, ui.card().classes("w-96"):
        ui.label("Desvincular sistema").classes("font-semibold text-lg")
        unlink_select = ui.select([], label="Sistema").classes("w-full").props("data-testid=group-unlink-select")
        unlink_target: dict = {"name": None}

        def confirm_unlink() -> None:
            directory.unlink_group_from_system(unlink_target["name"], unlink_select.value, user)
            unlink_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=unlink_dialog.close).props("flat")
            ui.button("Desvincular", icon="link_off", on_click=confirm_unlink).props("data-testid=confirm-group-unlink")

    def open_unlink(name: str, slugs: list[str]) -> None:
        unlink_target["name"] = name
        unlink_select.set_options(slugs, value=None)
        unlink_dialog.open()

    with ui.dialog() as gdelete_dialog, ui.card().classes("w-96"):
        ui.label("Excluir grupo").classes("font-semibold text-lg")
        gdelete_message = ui.label("").classes("text-sm text-gray-600")
        gdelete_target: dict = {"name": None}

        def confirm_group_delete() -> None:
            directory.delete_group(gdelete_target["name"], user)
            gdelete_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=gdelete_dialog.close).props("flat")
            ui.button("Excluir", icon="delete", on_click=confirm_group_delete).props("color=negative data-testid=confirm-group-delete")

    def open_delete(name: str) -> None:
        gdelete_target["name"] = name
        gdelete_message.set_text(f"Excluir o grupo '{name}'? Membros perdem o acesso aos sistemas vinculados.")
        gdelete_dialog.open()

    with ui.row().classes("mb-3 gap-2"):
        ui.button("Novo grupo", icon="add", on_click=open_group_dialog)
        ui.button("Adicionar membro a um grupo", icon="person_add", on_click=open_member_dialog)
        ui.button("Vincular a sistema", icon="link", on_click=open_link_dialog)

    listing = ui.column().classes("w-full max-w-3xl gap-2")
    refresh()


def _llm_keys_panel(user: User) -> None:
    def refresh() -> None:
        keys_box.clear()
        with keys_box:
            for item in provider_keys.list_keys():
                provider = item["provider"]
                definition = catalog.get_provider(provider) or {}
                models = definition.get("models") or []
                with ui.card().classes("w-full max-w-3xl").props(f"data-testid=key-card:{provider}"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("vpn_key").classes("text-gray-500")
                        ui.label(item["label"]).classes("font-semibold")
                        ui.label(provider).classes("text-xs text-gray-500")
                        ui.badge("preset" if definition.get("is_preset") else definition.get("kind", "")).props("color=blue-grey")
                        ui.badge("configurada" if item["configured"] else "sem chave").props(
                            "color=positive" if item["configured"] else "color=grey"
                        )
                    if definition.get("base_url"):
                        ui.label(definition["base_url"]).classes("text-xs text-gray-500")
                    ui.label(f"modelos: {', '.join(models) or '—'}").classes("text-xs text-gray-500")
                    with ui.row().classes("gap-2"):
                        ui.button("Cadastrar/Trocar", icon="key", on_click=lambda p=provider: open_key_dialog(p)).props("dense outline data-testid=key-set")
                        ui.button("Remover", icon="delete", on_click=lambda p=provider: ask_remove_key(p)).props("dense outline color=negative data-testid=key-remove")
                        ui.button("Testar", icon="science", on_click=lambda p=provider: do_test(p)).props("dense outline data-testid=key-test")
                        ui.button("Buscar modelos", icon="sync", on_click=lambda p=provider: do_discover(p)).props("dense outline data-testid=provider-models")
                        ui.button("Editar", icon="edit", on_click=lambda p=provider: open_edit_provider(p)).props("dense outline data-testid=provider-edit")
                        if not definition.get("is_preset"):
                            ui.button("Excluir provedor", icon="delete_forever", on_click=lambda p=provider: ask_remove_provider(p)).props("dense outline color=negative data-testid=provider-remove")

    key_target: dict = {"provider": None}

    with ui.dialog() as key_dialog, ui.card().classes("w-96"):
        key_label = ui.label("").classes("font-semibold text-lg")
        key_input = ui.input("Chave de API", password=True).classes("w-full").props("data-testid=key-input")

        def save_key() -> None:
            provider_keys.set_key(key_target["provider"], key_input.value, actor=user)
            key_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=key_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=save_key).props("data-testid=confirm-key-set")

    def open_key_dialog(provider: str) -> None:
        key_target["provider"] = provider
        key_label.set_text(f"Chave do provedor {provider}")
        key_input.set_value("")
        key_dialog.open()

    with ui.dialog() as remove_key_dialog, ui.card().classes("w-96"):
        ui.label("Remover chave").classes("font-semibold text-lg")
        remove_key_message = ui.label("").classes("text-sm text-gray-600")
        remove_key_target: dict = {"provider": None}

        def confirm_remove_key() -> None:
            provider_keys.remove_key(remove_key_target["provider"], actor=user)
            remove_key_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=remove_key_dialog.close).props("flat")
            ui.button("Remover", icon="delete", on_click=confirm_remove_key).props("color=negative data-testid=confirm-key-remove")

    def ask_remove_key(provider: str) -> None:
        remove_key_target["provider"] = provider
        remove_key_message.set_text(f"Remover a chave do provedor '{provider}'?")
        remove_key_dialog.open()

    def do_test(provider: str) -> None:
        ok, message = provider_keys.test_stored_key(provider)
        ui.notify(f"{provider}: {message}", type="positive" if ok else "negative")

    def do_discover(provider: str) -> None:
        try:
            models = catalog.discover_models(provider, actor=user)
        except catalog.DiscoveryFailed as exc:
            ui.notify(f"{provider}: {exc}", type="negative")
            return
        refresh()
        ui.notify(f"{provider}: {len(models)} modelo(s) encontrados", type="positive")

    with ui.dialog() as new_provider_dialog, ui.card().classes("w-96"):
        ui.label("Novo provedor").classes("font-semibold text-lg")
        np_id = ui.input("Id (kebab-case)").classes("w-full").props("data-testid=provider-id")
        np_label = ui.input("Rótulo").classes("w-full").props("data-testid=provider-label")
        np_kind = ui.select(["openai-compatible", "native"], value="openai-compatible", label="Tipo").classes("w-full").props("data-testid=provider-kind")
        np_base = ui.input("Base URL (OpenAI-compatible)").classes("w-full").props("data-testid=provider-base-url")
        np_feedback = ui.label("").classes("text-sm")

        def create_provider_action() -> None:
            try:
                catalog.create_provider(np_id.value, np_label.value, np_kind.value, np_base.value, actor=user)
            except (catalog.InvalidProvider, Exception) as exc:
                np_feedback.classes(remove="text-green-600", add="text-red-600").set_text(str(exc))
                return
            new_provider_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=new_provider_dialog.close).props("flat")
            ui.button("Criar provedor", icon="add", on_click=create_provider_action).props("data-testid=confirm-provider-create")

    def open_new_provider() -> None:
        np_id.set_value("")
        np_label.set_value("")
        np_kind.set_value("openai-compatible")
        np_base.set_value("")
        np_feedback.set_text("")
        new_provider_dialog.open()

    edit_target: dict = {"provider": None}

    with ui.dialog() as edit_provider_dialog, ui.card().classes("w-96"):
        ui.label("Editar provedor").classes("font-semibold text-lg")
        ep_label = ui.input("Rótulo").classes("w-full").props("data-testid=provider-edit-label")
        ep_base = ui.input("Base URL").classes("w-full").props("data-testid=provider-edit-base-url")
        ep_models = ui.input("Modelos (separados por vírgula)").classes("w-full").props("data-testid=provider-edit-models")

        def save_provider() -> None:
            models = [m.strip() for m in ep_models.value.split(",") if m.strip()]
            catalog.update_provider(edit_target["provider"], ep_label.value, ep_base.value, models=models, actor=user)
            edit_provider_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=edit_provider_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=save_provider).props("data-testid=confirm-provider-edit")

    def open_edit_provider(provider: str) -> None:
        definition = catalog.get_provider(provider) or {}
        edit_target["provider"] = provider
        ep_label.set_value(definition.get("label", ""))
        ep_base.set_value(definition.get("base_url") or "")
        ep_models.set_value(", ".join(definition.get("models") or []))
        edit_provider_dialog.open()

    with ui.dialog() as remove_provider_dialog, ui.card().classes("w-96"):
        ui.label("Excluir provedor").classes("font-semibold text-lg")
        remove_provider_message = ui.label("").classes("text-sm text-gray-600")
        remove_provider_target: dict = {"provider": None}

        def confirm_remove_provider() -> None:
            catalog.delete_provider(remove_provider_target["provider"], actor=user)
            remove_provider_dialog.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=remove_provider_dialog.close).props("flat")
            ui.button("Excluir", icon="delete", on_click=confirm_remove_provider).props("color=negative data-testid=confirm-provider-remove")

    def ask_remove_provider(provider: str) -> None:
        remove_provider_target["provider"] = provider
        remove_provider_message.set_text(f"Excluir o provedor '{provider}'?")
        remove_provider_dialog.open()

    ui.label("Catálogo de provedores e chaves (global por provedor).").classes("text-sm text-gray-500 mb-2")
    ui.button("Novo provedor", icon="add", on_click=open_new_provider).classes("mb-3").props("data-testid=provider-new")
    keys_box = ui.column().classes("w-full")
    refresh()


def _audit_panel() -> None:
    def refresh() -> None:
        entries_box.clear()
        with entries_box:
            entries = audit.list_global(
                limit=200,
                actor_email=actor_filter.value or None,
                resource_type=resource_filter.value if resource_filter.value else None,
                action=action_filter.value or None,
            )
            if not entries:
                ui.label("Nenhuma ação de gestão registrada ainda.").classes("text-gray-500 text-sm")
            for entry in entries:
                details = entry["details"] or {}
                with ui.row().classes("w-full items-center gap-2 text-sm").props("data-testid=audit-entry"):
                    ui.icon("history").classes("text-gray-500")
                    ui.label(entry["action"]).classes("font-semibold")
                    ui.label(f"{entry['resource_type']} {entry['resource_id'] or ''}").classes("text-gray-600")
                    ui.label(entry["actor_email"] or "sistema").classes("text-xs text-gray-500")
                    ui.label(entry["created_at"][:19].replace("T", " ")).classes("text-xs text-gray-400")
                    if details:
                        ui.label(str(details)).classes("text-xs text-gray-400")

    with ui.row().classes("w-full items-center gap-2 mb-3"):
        actor_filter = ui.input("Autor (e-mail)").classes("w-56").props("data-testid=audit-actor")
        resource_filter = ui.select(["", "user", "group", "system", "connection", "checkpoint", "provider_key", "guidelines"], value="", label="Recurso").classes("w-48").props("data-testid=audit-resource")
        action_filter = ui.input("Ação").classes("w-56").props("data-testid=audit-action")
        actor_filter.on_value_change(refresh)
        resource_filter.on_value_change(refresh)
        action_filter.on_value_change(refresh)

    entries_box = ui.column().classes("w-full max-w-4xl gap-1")
    refresh()