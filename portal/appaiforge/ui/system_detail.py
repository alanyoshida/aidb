"""Detalhe do sistema: estado, provedor e conexões de banco (specs system-management, db-connections)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nicegui import ui

from ..models import System
from ..rbac import can_access_system, can_manage_system
from ..services import catalog, connections, network_policy
from ..services.systems import get_system, rename_system, revoke_inference_access, set_provider
from .common import get_current_user, notify, render_header


def _stamp(iso: str) -> str:
    """Formata um `created_at` ISO (UTC) no fuso de exibição, como "dd/mm HH:MM"
    — mesma convenção do chat (`ui/chat.py:_stamp`)."""
    from ..config import get_settings

    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    try:
        local = dt.astimezone(ZoneInfo(get_settings().display_timezone))
    except ZoneInfoNotFoundError:
        local = dt
    return local.strftime("%d/%m %H:%M")

_STATUS_LABEL = {"provisioning": "provisionando", "active": "ativo", "error": "erro", "archived": "arquivado"}
_STATUS_COLOR = {"active": "positive", "provisioning": "warning", "error": "negative"}


def _catalog_provider_ids() -> list[str]:
    ids = [p["id"] for p in catalog.list_providers()]
    return ids or ["glm"]


def _catalog_models(provider_id: str, current: str | None = None) -> list[str]:
    provider = catalog.get_provider(provider_id)
    models = list(provider["models"]) if provider else []
    if current and current in models:
        models.remove(current)
        models.insert(0, current)
    elif current:
        models.insert(0, current)
    return models


def register() -> None:
    @ui.page("/systems/{system_id}")
    def system_page(system_id: str) -> None:
        user = get_current_user()
        if user is None:
            ui.navigate.to("/login")
            return
        system = get_system(system_id)
        if system is None or not can_access_system(user, system.id):
            ui.label("Sistema não encontrado ou acesso negado.").classes("text-red-600 m-8")
            return

        render_header(user)
        with ui.row().classes("mx-4 mt-4 items-center gap-1 text-sm"):
            ui.link("Sistemas", "/").classes("text-gray-500")
            ui.icon("chevron_right").classes("text-gray-500 text-sm")
            breadcrumb_label = ui.label(system.name).classes("text-gray-300")
        # identidade à esquerda, ação principal à direita na mesma faixa
        with ui.row().classes("mx-4 mt-1 w-full items-center justify-between no-wrap"):
            with ui.column().classes("gap-1"):
                name_label = ui.label(system.name).classes("text-2xl font-bold")
                provider_label = None
                with ui.row().classes("items-center"):
                    ui.label(f"/{system.slug}").classes("text-gray-500")
                    status_badge = ui.badge(_STATUS_LABEL.get(system.status.value, system.status.value))
                    if can_manage_system(user, system):
                        provider_label = ui.label(f"provedor: {system.provider} / modelo: {system.model}").classes("text-sm text-gray-600")
            open_btn = ui.button("Abrir app", icon="open_in_new", on_click=lambda: ui.navigate.to(f"/entry/{system.slug}", new_tab=True)).props("size=lg unelevated data-testid=open-app").classes("mr-8")
        open_btn.set_visibility(system.status.value == "active")

        def refresh_status() -> None:
            fresh = get_system(system.id)
            if fresh is None:
                return
            label = _STATUS_LABEL.get(fresh.status.value, fresh.status.value)
            if status_badge.text != label:
                status_badge.set_text(label)
                status_badge.props(f"color={_STATUS_COLOR.get(fresh.status.value, 'grey')}")
            open_btn.set_visibility(fresh.status.value == "active")

        ui.timer(2.0, refresh_status)

        if not can_manage_system(user, system):
            return

        with ui.tabs().classes("mx-4 w-full") as tabs:
            chat_tab = ui.tab("chat", label="Chat", icon="chat")
            editor_tab = ui.tab("editor", label="Editor", icon="code").props("data-testid=tab-editor")
            conn_tab = ui.tab("conn", label="Conexões", icon="storage")
            net_tab = ui.tab("net", label="Domínios", icon="public").props("data-testid=tab-domains")
            ckpt_tab = ui.tab("ckpt", label="Checkpoints", icon="history")
            cfg_tab = ui.tab("cfg", label="Configurações", icon="settings")
            audit_tab = ui.tab("audit", label="Auditoria", icon="shield")

        with ui.tab_panels(tabs, value=chat_tab).classes("mx-4 w-full"):
            with ui.tab_panel(chat_tab):
                from .chat import render_chat

                # sessão gravada na URL por _switch_session (ver chat.py) — sobrevive
                # ao reload que trocar de tema força, que senão sempre derrubava a
                # sessão ativa no meio de uma conversa (achado do critique)
                initial_session_id = ui.context.client.request.query_params.get("session")
                render_chat(system, user, initial_session_id)
            with ui.tab_panel(editor_tab):
                _render_editor(system, user)
            with ui.tab_panel(conn_tab):
                _render_connections(system, user)
            with ui.tab_panel(net_tab):
                _render_network(system, user)
            with ui.tab_panel(ckpt_tab):
                _render_checkpoints(system, user)
            with ui.tab_panel(cfg_tab):
                _render_configuration(system, user, name_label, breadcrumb_label, provider_label)
            with ui.tab_panel(audit_tab):
                _render_gate_history(system)
                _render_management_audit(system)
                _render_usage(system)


def _render_configuration(system, user, name_label, breadcrumb_label, provider_label) -> None:
    """Identidade (nome, provedor/modelo), rede de saída e ciclo de vida do
    sistema (specs system-management, https-forward-proxy)."""
    ui.label("Rede de saída do agente").classes("font-semibold mt-2")
    with ui.row().classes("items-center gap-6 mb-2"):
        with ui.column().classes("gap-0"):
            ui.switch(
                "Acesso à internet", value=system.internet_enabled,
                on_change=lambda e: (
                    network_policy.set_internet_enabled(system.id, e.value),
                    notify("Acesso à internet " + ("habilitado" if e.value else "desabilitado — só o broker de inferência continua alcançável") + ".", kind="positive"),
                ),
            ).props("data-testid=toggle-internet-enabled")
            ui.label(
                "Desligado, o proxy de saída não libera nenhum destino externo; o broker de inferência "
                "(quando habilitado) não é afetado — ele nunca passa por este proxy."
            ).classes("text-xs text-gray-500")
        with ui.column().classes("gap-0"):
            ui.switch(
                "Modo restrito", value=system.restricted_network,
                on_change=lambda e: (
                    network_policy.set_restricted_network(system.id, e.value),
                    notify("Modo restrito " + ("ligado — só os domínios da aba \"Domínios\" são liberados." if e.value else "desligado — voltou a usar a allow-list padrão."), kind="positive"),
                ),
            ).props("data-testid=toggle-restricted-network")
            ui.label(
                "Ligado, substitui a allow-list padrão (provedor de LLM/broker + registros de pacote) "
                "pela lista cadastrada na aba \"Domínios\" — só ela passa a valer."
            ).classes("text-xs text-gray-500")

    with ui.row().classes("gap-2"):
        ui.button("Renomear sistema", icon="edit", on_click=lambda: open_rename_dialog()).props("dense outline data-testid=rename-system")
        ui.button("Editar provedor/modelo", icon="bolt", on_click=lambda: open_provider_dialog()).props("dense outline data-testid=edit-provider")

    with ui.dialog() as rename_dialog, ui.card().classes("w-96"):
        ui.label("Renomear sistema").classes("font-semibold text-lg")
        rename_input = ui.input("Nome").classes("w-full").props("data-testid=rename-system-name")

        def do_rename() -> None:
            rename_system(system, rename_input.value, user)
            new_name = rename_input.value.strip()
            name_label.set_text(new_name)
            breadcrumb_label.set_text(new_name)
            rename_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=rename_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=do_rename).props("data-testid=confirm-rename-system")

    def open_rename_dialog() -> None:
        rename_input.set_value(system.name)
        rename_dialog.open()

    with ui.dialog() as provider_dialog, ui.card().classes("w-96"):
        ui.label("Provedor e modelo").classes("font-semibold text-lg")
        provider_select = ui.select(_catalog_provider_ids(), value=system.provider, label="Provedor").classes("w-full").props("data-testid=edit-provider-select")
        model_select = ui.select(_catalog_models(system.provider, system.model), value=system.model, label="Modelo").classes("w-full").props("data-testid=edit-model-select")

        def on_provider_change() -> None:
            model_select.set_options(_catalog_models(provider_select.value), value=None)

        provider_select.on_value_change(on_provider_change)
        provider_feedback = ui.label("").classes("text-sm")

        def do_save_provider() -> None:
            if not model_select.value:
                provider_feedback.classes(remove="text-green-600", add="text-red-600").set_text(
                    "escolha um modelo (se a lista estiver vazia, cadastre/descubra modelos em Administração → Provedores de LLM)"
                )
                return
            set_provider(system.id, provider_select.value, model_select.value, actor=user)
            if provider_label is not None:
                provider_label.set_text(f"provedor: {provider_select.value} / modelo: {model_select.value}")
            provider_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=provider_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=do_save_provider).props("data-testid=confirm-provider")

    def open_provider_dialog() -> None:
        provider_select.set_value(system.provider)
        model_select.set_options(_catalog_models(system.provider, system.model), value=system.model)
        provider_feedback.set_text("")
        provider_dialog.open()

    with ui.dialog() as revoke_dialog, ui.card().classes("w-96"):
        ui.label("Revogar acesso de inferência").classes("font-semibold text-lg")
        ui.label(
            "O token atual do sistema deixa de valer e um novo é gerado. "
            "O container será recriado com o novo token; execuções em andamento serão interrompidas."
        ).classes("text-sm text-gray-600")
        revoke_feedback = ui.label("").classes("text-sm")

        def do_revoke() -> None:
            try:
                revoke_inference_access(system.id, actor=user)
            except Exception as exc:  # noqa: BLE001 - feedback direto ao operador
                revoke_feedback.classes(remove="text-green-600", add="text-red-600").set_text(str(exc))
                return
            revoke_dialog.close()
            notify("Acesso de inferência revogado; o container será recriado com o novo token.", kind="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=revoke_dialog.close).props("flat")
            ui.button("Revogar acesso", icon="key_off", on_click=do_revoke).props("color=negative data-testid=confirm-revoke-access")

    def open_revoke_dialog() -> None:
        revoke_feedback.set_text("")
        revoke_dialog.open()

    # ciclo de vida: arquivar (dono) e excluir definitivamente (admin, arquivado)
    with ui.row().classes("mt-4"):

        def archive() -> None:
            from ..provisioning import archive_system

            archive_system(system)
            ui.navigate.to("/")

        ui.button("Arquivar sistema", icon="archive", on_click=archive).props("color=warning outline data-testid=archive-system")

        ui.button("Revogar acesso de inferência", icon="key_off", on_click=open_revoke_dialog).props("color=negative outline data-testid=revoke-access")

        if user.is_admin and system.status.value == "archived":

            def delete() -> None:
                from ..provisioning import delete_system

                delete_system(system)
                ui.navigate.to("/")

            ui.button("Excluir definitivamente", icon="delete_forever", on_click=delete).props("color=negative data-testid=delete-system")


def _render_connections(system, user) -> None:
    """Conexões de banco: lista + criar/editar/remover (spec db-connections)."""
    manage = can_manage_system(user, system)
    ui.label("Bancos de dados que o agente e a app podem acessar").classes("text-sm text-gray-500 mb-2")

    _KIND_OPTIONS = {"PostgreSQL": "postgres", "MySQL": "mysql", "BigQuery": "bigquery"}
    _KIND_DEFAULT_PORT = {"postgres": 5432, "mysql": 3306, "bigquery": 0}

    with ui.dialog() as conn_dialog, ui.card().classes("w-96"):
        ui.label("Nova conexão").classes("font-semibold text-lg")
        ckind = ui.select(list(_KIND_OPTIONS.keys()), value="PostgreSQL", label="Tipo").classes("w-full").props("data-testid=conn-kind")
        cname = ui.input("Nome").classes("w-full").props("data-testid=conn-name")

        with ui.column().classes("w-full") as c_sql_fields:
            chost = ui.input("Host").classes("w-full").props("data-testid=conn-host")
            cport = ui.number("Porta", value=5432).classes("w-full").props("data-testid=conn-port")
            cdb = ui.input("Banco").classes("w-full").props("data-testid=conn-database")
            cuser = ui.input("Usuário").classes("w-full").props("data-testid=conn-user")
            cpass = ui.input("Senha", password=True).classes("w-full").props("data-testid=conn-password")

        with ui.column().classes("w-full") as c_bq_fields:
            cbq_project = ui.input("Project ID").classes("w-full").props("data-testid=conn-bq-project")
            cbq_dataset = ui.input("Dataset").classes("w-full").props("data-testid=conn-bq-dataset")
            cbq_sa_json = ui.textarea("Service Account JSON").classes("w-full").props("data-testid=conn-bq-sa-json")

        cdesc = ui.input("Descrição (opcional)").classes("w-full").props("data-testid=conn-description")
        caccess_mode = ui.select(
            {"read_write": "Leitura e escrita", "read_only": "Somente leitura"},
            value="read_write", label="Modo de acesso",
        ).classes("w-full").props("data-testid=conn-access-mode")

        c_bq_fields.set_visibility(False)
        feedback = ui.label("").classes("text-sm")

        def _on_kind_change(e) -> None:
            kind_key = _KIND_OPTIONS.get(e.value, "postgres")
            is_bq = kind_key == "bigquery"
            c_sql_fields.set_visibility(not is_bq)
            c_bq_fields.set_visibility(is_bq)
            if not is_bq:
                cport.set_value(_KIND_DEFAULT_PORT[kind_key])

        ckind.on("update:model-value", _on_kind_change)

        def add_conn() -> None:
            kind_key = _KIND_OPTIONS.get(ckind.value, "postgres")
            if kind_key == "bigquery":
                host, port, database, username, password = (
                    cbq_project.value, 0, cbq_dataset.value, "", cbq_sa_json.value
                )
            else:
                host = chost.value
                port = int(cport.value or _KIND_DEFAULT_PORT[kind_key])
                database, username, password = cdb.value, cuser.value, cpass.value
            try:
                connections.register_connection(
                    system, cname.value, host, port, database, username, password, kind=kind_key, actor=user,
                    description=cdesc.value or None, access_mode=caccess_mode.value or "read_write",
                )
            except connections.ConnectionFailed as exc:
                feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"teste de conexão falhou: {exc}")
                return
            except connections.NameTaken:
                feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"conexão '{cname.value}' já existe")
                return
            feedback.classes(remove="text-red-600", add="text-green-600").set_text("conexão cadastrada")
            refresh_conns()
            conn_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=conn_dialog.close).props("flat")
            ui.button("Testar e salvar", icon="check_circle", on_click=add_conn).props("data-testid=save-connection")

    def open_conn_dialog() -> None:
        ckind.set_value("PostgreSQL")
        for field in (cname, chost, cdb, cuser, cpass, cbq_project, cbq_dataset, cbq_sa_json):
            field.set_value("")
        cdesc.set_value("")
        caccess_mode.set_value("read_write")
        cport.set_value(5432)
        c_sql_fields.set_visibility(True)
        c_bq_fields.set_visibility(False)
        feedback.set_text("")
        conn_dialog.open()

    _CONN_STATUS_COLOR = {"healthy": "positive", "degraded": "negative", "unknown": "neutral"}
    _CONN_STATUS_LABEL = {"healthy": "saudável", "degraded": "degradada", "unknown": "desconhecido"}
    _KIND_LABEL = {"postgres": "PostgreSQL", "mysql": "MySQL", "bigquery": "BigQuery"}
    edit_target: dict = {"id": None}

    with ui.dialog() as edit_dialog, ui.card().classes("w-96"):
        ui.label("Editar conexão").classes("font-semibold text-lg")
        ekind = ui.select(list(_KIND_OPTIONS.keys()), value="PostgreSQL", label="Tipo").classes("w-full").props("data-testid=edit-conn-kind")
        ename = ui.input("Nome").classes("w-full").props("data-testid=edit-conn-name")

        with ui.column().classes("w-full") as e_sql_fields:
            ehost = ui.input("Host").classes("w-full").props("data-testid=edit-conn-host")
            eport = ui.number("Porta", value=5432).classes("w-full").props("data-testid=edit-conn-port")
            edb = ui.input("Banco").classes("w-full").props("data-testid=edit-conn-database")
            euser = ui.input("Usuário").classes("w-full").props("data-testid=edit-conn-user")
            epass = ui.input("Nova senha (opcional)", password=True).classes("w-full").props("data-testid=edit-conn-password")

        with ui.column().classes("w-full") as e_bq_fields:
            ebq_project = ui.input("Project ID").classes("w-full").props("data-testid=edit-conn-bq-project")
            ebq_dataset = ui.input("Dataset").classes("w-full").props("data-testid=edit-conn-bq-dataset")
            ebq_sa_json = ui.textarea("Novo Service Account JSON (opcional)").classes("w-full").props("data-testid=edit-conn-bq-sa-json")
            ebq_email = ui.label("").classes("text-xs text-gray-500")

        edesc = ui.input("Descrição (opcional)").classes("w-full").props("data-testid=edit-conn-description")
        eaccess_mode = ui.select(
            {"read_write": "Leitura e escrita", "read_only": "Somente leitura"},
            value="read_write", label="Modo de acesso",
        ).classes("w-full").props("data-testid=edit-conn-access-mode")

        e_bq_fields.set_visibility(False)
        edit_feedback = ui.label("").classes("text-sm")

        def _on_ekind_change(e) -> None:
            kind_key = _KIND_OPTIONS.get(e.value, "postgres")
            is_bq = kind_key == "bigquery"
            e_sql_fields.set_visibility(not is_bq)
            e_bq_fields.set_visibility(is_bq)
            if not is_bq:
                eport.set_value(_KIND_DEFAULT_PORT[kind_key])

        ekind.on("update:model-value", _on_ekind_change)

        def save_edit() -> None:
            kind_key = _KIND_OPTIONS.get(ekind.value, "postgres")
            if kind_key == "bigquery":
                host, port, database = ebq_project.value, 0, ebq_dataset.value
                username, password = "", ebq_sa_json.value or None
            else:
                host = ehost.value
                port = int(eport.value or _KIND_DEFAULT_PORT[kind_key])
                database, username, password = edb.value, euser.value, epass.value or None
            try:
                connections.update_connection(
                    system, edit_target["id"], ename.value, host, port,
                    database, username, password=password, kind=kind_key, actor=user,
                    description=edesc.value or None, access_mode=eaccess_mode.value or "read_write",
                )
            except connections.ConnectionFailed as exc:
                edit_feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"teste de conexão falhou: {exc}")
                return
            except connections.NameTaken:
                edit_feedback.classes(remove="text-green-600", add="text-red-600").set_text(f"conexão '{ename.value}' já existe")
                return
            edit_feedback.classes(remove="text-red-600", add="text-green-600").set_text("conexão atualizada")
            refresh_conns()
            edit_dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=edit_dialog.close).props("flat")
            ui.button("Testar e salvar", icon="check_circle", on_click=save_edit).props("data-testid=save-connection-edit")

    def open_edit_dialog(c: dict) -> None:
        edit_target["id"] = c["id"]
        kind = c.get("kind", "postgres")
        ekind.set_value(_KIND_LABEL.get(kind, "PostgreSQL"))
        ename.set_value(c["name"])
        edesc.set_value(c.get("description") or "")
        eaccess_mode.set_value(c.get("access_mode") or "read_write")
        is_bq = kind == "bigquery"
        e_sql_fields.set_visibility(not is_bq)
        e_bq_fields.set_visibility(is_bq)
        if is_bq:
            ebq_project.set_value(c["host"])
            ebq_dataset.set_value(c["database"])
            ebq_sa_json.set_value("")
            ebq_email.set_text(f"Service account: {c['username']}" if c.get("username") else "")
        else:
            ehost.set_value(c["host"])
            eport.set_value(c["port"])
            edb.set_value(c["database"])
            euser.set_value(c["username"])
            epass.set_value("")
        edit_feedback.set_text("")
        edit_dialog.open()

    remove_target: dict = {"id": None}

    with ui.dialog() as remove_dialog, ui.card().classes("w-96"):
        ui.label("Remover conexão").classes("font-semibold text-lg")
        remove_message = ui.label("").classes("text-sm text-gray-600")

        def confirm_remove() -> None:
            connections.remove_connection(system, remove_target["id"], actor=user)
            remove_dialog.close()
            refresh_conns()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=remove_dialog.close).props("flat")
            ui.button("Remover", icon="delete", on_click=confirm_remove).props("color=negative data-testid=confirm-remove-connection")

    def ask_remove(c: dict) -> None:
        remove_target["id"] = c["id"]
        remove_message.set_text(
            f"Remover a conexão '{c['name']}'? O agente e a app deixarão de acessar este banco."
        )
        remove_dialog.open()

    ui.button("Nova conexão", icon="add", on_click=open_conn_dialog).classes("mb-3")

    conns_box = ui.column().classes("w-full max-w-3xl")

    def refresh_conns() -> None:
        conns_box.clear()
        conns = connections.list_connections(system.id)
        with conns_box:
            if not conns:
                ui.label("Nenhuma conexão cadastrada ainda.").classes("text-gray-500 text-sm")
            for c in conns:
                with ui.card().classes("w-full").props(f"data-testid=conn-card:{c['name']}"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"{c['name']}").classes("font-semibold")
                        status = c.get("status", "unknown")
                        cor = _CONN_STATUS_COLOR.get(status, "neutral")
                        # só o neutro precisa de texto próprio; os coloridos já
                        # vêm com o par "on-" certo pelo CSS do tema
                        texto_badge = " text-color=neutraltext" if cor == "neutral" else ""
                        ui.badge(
                            _CONN_STATUS_LABEL.get(status, status)
                        ).props(f"color={cor}{texto_badge} data-testid=conn-status-badge")
                        if c.get("access_mode") == "read_only":
                            ui.badge("somente-leitura").props("color=info data-testid=conn-access-mode-badge")
                    if c.get("description"):
                        ui.label(c["description"]).classes("text-sm text-gray-500 italic")
                    if c.get("kind") == "bigquery":
                        ui.label(f"bigquery · {c['host']}/{c['database']} ({c['username']})").classes("text-sm text-gray-600")
                    else:
                        ui.label(f"{c['kind']} · {c['username']}@{c['host']}:{c['port']}/{c['database']}").classes("text-sm text-gray-600")
                    if manage:
                        with ui.row().classes("gap-2"):
                            ui.button("Editar", icon="edit", on_click=lambda c=c: open_edit_dialog(c)).props("dense outline data-testid=conn-edit")
                            ui.button("Remover", icon="delete", on_click=lambda c=c: ask_remove(c)).props("dense outline color=negative data-testid=conn-remove")

    refresh_conns()


def _render_network(system, user) -> None:
    """Lista de domínios do modo restrito do proxy HTTP(S) de saída (change
    `agent-https-forward-proxy`, D7/D8) — mesmo nível de acesso da aba
    Conexões: quem gerencia o sistema cadastra os domínios dele. Só tem
    efeito quando "Modo restrito" está ligado (aba Configurações), mas a
    lista pode ser editada com o modo desligado também."""
    manage = can_manage_system(user, system)
    ui.label(
        "Domínios liberados quando o \"Modo restrito\" está ligado (aba Configurações) — "
        "substituem por completo a allow-list padrão (provedor de LLM/broker + registros de pacote)."
    ).classes("text-sm text-gray-500 mb-2")

    domains_box = ui.column().classes("w-full gap-1")

    def refresh_domains() -> None:
        domains_box.clear()
        domains = network_policy.list_allowed_domains(system.id)
        with domains_box:
            if not domains:
                ui.label("Nenhum domínio cadastrado.").classes("text-sm text-gray-500")
            for d in domains:
                with ui.row().classes("items-center gap-2"):
                    ui.label(d["domain"]).classes("font-mono text-sm").props("data-testid=domain-item")
                    if manage:
                        ui.button(
                            icon="delete", on_click=lambda d=d: remove_domain(d["id"])
                        ).props("dense flat color=negative data-testid=domain-remove")

    def remove_domain(domain_id: str) -> None:
        network_policy.remove_allowed_domain(system.id, domain_id)
        refresh_domains()

    if manage:
        with ui.row().classes("items-center gap-2 mt-2"):
            new_domain = ui.input("Novo domínio (ex.: api.exemplo.com)").classes("w-80").props("data-testid=new-domain")

            def add_domain() -> None:
                value = (new_domain.value or "").strip()
                if not value:
                    return
                result = network_policy.add_allowed_domain(system.id, value, author_id=user.id)
                new_domain.set_value("")
                if result is None:
                    notify(f"'{value}' já está na lista.", kind="warning")
                refresh_domains()

            ui.button("Adicionar", icon="add", on_click=add_domain).props("data-testid=add-domain")

    refresh_domains()


def _render_editor(system, user) -> None:
    """Aba Editor: árvore do projeto gerado (`<workspace>/app`) à esquerda,
    conteúdo somente-leitura à direita (capability workspace-viewer)."""
    from .. import workspace_files
    from . import theme as _theme

    mode, _accent = _theme.parse_key(user.theme)
    # tema do CodeMirror segue o modo do portal: sem isso, o painel aparece
    # sempre com fundo claro (basicLight), destoando do resto da página no
    # modo escuro/pastel.
    cm_theme = "vscodeDark" if mode == "dark" else "vscodeLight"

    state: dict = {"selected": None}

    with ui.splitter(value=25).classes("w-full h-[32rem]") as splitter:
        with splitter.before:
            tree_box = ui.column().classes("w-full h-full overflow-auto")
        with splitter.after:
            content_box = ui.column().classes("w-full h-full pl-4")

    def render_content() -> None:
        content_box.clear()
        with content_box:
            rel_path = state["selected"]
            if rel_path is None:
                ui.label("Selecione um arquivo na árvore para ver o conteúdo.").classes("text-gray-500 text-sm")
                return
            try:
                content = workspace_files.read_file(system, rel_path)
            except (ValueError, OSError):
                ui.label("Não foi possível ler este arquivo.").classes("text-gray-500 text-sm")
                return
            if content.binary:
                with ui.card().classes("w-full border border-amber-300 bg-amber-50 p-2").props("data-testid=editor-binary-warning"):
                    ui.label(f"Pré-visualização não disponível para {rel_path} (arquivo binário ou ilegível como texto).").classes("text-xs text-amber-800 font-medium")
                return
            with ui.row().classes("w-full items-center gap-2 q-mb-sm").props("data-testid=editor-file-header"):
                ui.icon(workspace_files.icon_for(rel_path)).classes("text-sm")
                ui.label(rel_path).classes("text-sm font-medium")
                if content.language:
                    ui.badge(content.language, color="grey-6").props("data-testid=editor-file-language")
            ui.codemirror(content.text or "", language=content.language, theme=cm_theme).props("data-testid=editor-content").classes("w-full h-full").disable()

    def select_file(e) -> None:
        state["selected"] = e.value
        render_content()

    def _node_ids(nodes: list[dict]) -> set[str]:
        ids: set[str] = set()
        for node in nodes:
            ids.add(node["id"])
            ids |= _node_ids(node.get("children", []))
        return ids

    def refresh_tree() -> None:
        """Reconstrói a árvore a partir do workspace atual. Preserva a seleção
        (D3: `id` é o caminho relativo, estável) quando o arquivo continuar
        existindo; limpa o painel quando ele sumiu.

        Só reconstrói quando a estrutura mudar: limpar e recriar a cada 2s
        derrubava cliques que caíam num nó prestes a ser removido."""
        nodes = workspace_files.list_tree(system)
        if state["selected"] is not None and state["selected"] not in _node_ids(nodes):
            state["selected"] = None
            render_content()
        fingerprint = json.dumps(nodes, sort_keys=True)
        if fingerprint == state.get("tree_fingerprint"):
            return
        state["tree_fingerprint"] = fingerprint
        tree_box.clear()
        with tree_box:
            if not nodes:
                ui.label("Nenhum arquivo gerado ainda.").props("data-testid=editor-empty").classes("text-gray-500 text-sm")
                return
            ui.tree(nodes, on_select=select_file).props("data-testid=editor-tree")

    refresh_tree()
    render_content()
    ui.timer(2.0, refresh_tree)


def _render_checkpoints(system, user) -> None:
    from .. import checkpoints as cp_service

    ui.label("Pontos salvos do código da app — restaure ou exclua").classes("text-sm text-gray-500 mb-2")

    def create_checkpoint() -> None:
        # record_checkpoint devolve None quando o git não tem nada para commitar;
        # sem aviso o botão parece quebrado.
        cp = cp_service.record_checkpoint(system, None, "checkpoint manual", author=user)
        if cp is None:
            notify("Nada mudou no workspace desde o último checkpoint.", "info")
            return
        notify(f"Checkpoint {cp.git_sha[:8]} criado.", "positive")
        refresh_cps()

    ui.button("Criar checkpoint agora", icon="add", on_click=create_checkpoint).props("outline dense")
    timeline_container = ui.column().classes("w-full max-w-3xl mt-2")

    delete_target: dict = {"id": None}

    with ui.dialog() as delete_dialog, ui.card().classes("w-96"):
        ui.label("Excluir checkpoint").classes("font-semibold text-lg")
        delete_message = ui.label("").classes("text-sm text-gray-600")

        def confirm_delete() -> None:
            cp_service.delete_checkpoint(system, delete_target["id"], actor=user)
            delete_dialog.close()
            refresh_cps()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=delete_dialog.close).props("flat")
            ui.button("Excluir", icon="delete", on_click=confirm_delete).props("color=negative data-testid=confirm-checkpoint-delete")

    def ask_delete(cp: dict) -> None:
        delete_target["id"] = cp["id"]
        delete_message.set_text(f"Excluir o checkpoint {cp['git_sha'][:8]}?")
        delete_dialog.open()

    def refresh_cps() -> None:
        timeline_container.clear()
        try:
            cps = cp_service.list_checkpoints(system)
        except Exception:
            cps = []
        with timeline_container:
            if not cps:
                ui.label("Nenhum checkpoint ainda.").classes("text-gray-500 text-sm")
                return
            with ui.timeline(side="right"):
                for cp in cps:

                    def do_rollback(sha=cp["git_sha"]) -> None:
                        cp_service.rollback(system, sha)
                        notify(f"workspace restaurado para {sha[:8]}", "positive")

                    with ui.timeline_entry(title=cp["git_sha"][:8], subtitle=_stamp(cp["created_at"]), icon="commit"):
                        ui.label(cp["message"][:140]).classes("text-sm")
                        with ui.row().classes("gap-2"):
                            ui.button("Restaurar", icon="restore", on_click=do_rollback).props("dense outline")
                            ui.button("Excluir", icon="delete", on_click=lambda cp=cp: ask_delete(cp)).props("dense outline color=negative data-testid=checkpoint-delete")

    refresh_cps()
    ui.timer(2.0, refresh_cps)


def _render_management_audit(system) -> None:
    """Ações de gestão deste sistema (capability management-audit)."""
    from ..services import audit

    ui.label("Ações de gestão").classes("text-lg font-semibold mt-6")
    ui.label("Alterações de conexões, provedor, nome e checkpoints deste sistema").classes("text-sm text-gray-500 mb-2")
    box = ui.column().classes("w-full max-w-3xl gap-1")

    def refresh() -> None:
        entries = audit.list_by_system(system.id, limit=30)
        box.clear()
        with box:
            if not entries:
                ui.label("Nenhuma ação de gestão ainda.").classes("text-gray-500 text-sm")
            for e in entries:
                with ui.row().classes("w-full items-center gap-2 text-sm"):
                    ui.icon("history").classes("text-gray-500")
                    ui.label(e["action"]).classes("font-semibold")
                    ui.label(f"{e['resource_type']} {e['resource_id'] or ''}").classes("text-gray-600")
                    ui.label(e["actor_email"] or "sistema").classes("text-xs text-gray-500")
                    ui.label(e["created_at"][:19].replace("T", " ")).classes("text-xs text-gray-400")

    refresh()
    ui.timer(2.0, refresh)


def _render_usage(system) -> None:
    from sqlalchemy import select

    from ..db import session_scope
    from ..models import AgentRun, TokenUsage

    ui.label("Uso de tokens").classes("text-lg font-semibold mt-6")
    ui.label("Consumo de LLM agrupado por execução, para acompanhar custo").classes("text-sm text-gray-500 mb-2")
    total_label = ui.label("").classes("text-sm font-semibold")
    detail_box = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh_usage() -> None:
        with session_scope() as s:
            rows = s.execute(
                select(TokenUsage, AgentRun.prompt)
                .outerjoin(AgentRun, AgentRun.id == TokenUsage.run_id)
                .where(TokenUsage.system_id == system.id)
                .order_by(TokenUsage.created_at.desc())
            ).all()
        total_in = sum(usage.input_tokens for usage, _ in rows)
        total_out = sum(usage.output_tokens for usage, _ in rows)
        total_label.set_text(f"total: {total_in:,} entrada / {total_out:,} saída")

        execs: dict[str, dict] = {}
        for usage, prompt in rows:
            group = execs.setdefault(
                usage.run_id,
                {"provider": usage.provider, "model": usage.model, "email": usage.user_email, "prompt": prompt, "tin": 0, "tout": 0},
            )
            group["tin"] += usage.input_tokens
            group["tout"] += usage.output_tokens

        grand_total = total_in + total_out
        detail_box.clear()
        with detail_box:
            if not execs:
                ui.label("Nenhum uso registrado ainda.").classes("text-gray-500 text-sm")
                return
            for run_id, group in execs.items():
                used = group["tin"] + group["tout"]
                share = (used / grand_total) if grand_total else 0.0
                with ui.card().classes("w-full"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("bolt").classes("text-gray-500")
                        ui.label(f"{group['provider']}/{group['model']}").classes("font-semibold text-sm")
                        ui.label((group["prompt"] or run_id)[:80]).classes("text-sm text-gray-600")
                        ui.label(f"{used:,} tokens").classes("text-sm")
                    ui.linear_progress(value=share).classes("w-full")
                    ui.label(
                        f"{group['tin']:,} entrada / {group['tout']:,} saída · {share * 100:.0f}% do total · "
                        f"{group['email'] or 'usuário removido'}"
                    ).classes("text-xs text-gray-500")

    refresh_usage()
    ui.timer(2.0, refresh_usage)


def _render_gate_history(system) -> None:
    """Histórico de decisões do gate (spec destructive-gate: auditoria)."""
    from .. import gate as gate_service

    ui.label("Gate de destrutivas").classes("text-lg font-semibold")
    ui.label("Decisões sobre comandos SQL que alteram ou apagam dados").classes("text-sm text-gray-500 mb-2")
    rows_box = ui.column().classes("w-full max-w-3xl")

    def refresh_gate() -> None:
        decisions = gate_service.list_decisions(system.id, limit=20)
        rows_box.clear()
        with rows_box:
            if not decisions:
                ui.label("Nenhuma decisão do gate ainda.").classes("text-gray-500 text-sm")
            for d in decisions:
                color = {"bloqueada": "text-red-600", "recusada": "text-orange-600", "aprovada": "text-green-700"}.get(d["decision"], "")
                autor = d["author_email"] or "sistema"
                with ui.row().classes("w-full items-center"):
                    ui.label(f"[{d['decision']}] {d['sql'][:70]}").classes(f"text-sm {color}")
                    ui.label(f"({d['origin']} · autor: {autor} · {_stamp(d['created_at'])})").classes("text-xs text-gray-500")

    refresh_gate()
    ui.timer(2.0, refresh_gate)
