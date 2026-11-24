"""Detalhe do sistema: estado, provedor e conexões de banco (specs system-management, db-connections)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nicegui import ui

from ..models import System
from ..rbac import can_access_system, can_manage_system
from ..services import catalog, connections, network_policy
from ..services.systems import get_system, rename_system, revoke_inference_access, set_provider
from .common import get_current_user, redirect_to_login, notify, render_header


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
            redirect_to_login()
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
        # identidade à esquerda, ação principal à direita na mesma faixa — sem
        # no-wrap: em telas estreitas o título já quebra em duas linhas, e o
        # botão (size=lg, rótulo de duas palavras) virava um bloco alto e
        # espremido do lado do título quebrado (achado do critique). Sem
        # no-wrap, o botão desce pra própria linha quando não cabe ao lado.
        with ui.row().classes("mx-4 mt-1 w-full items-center justify-between gap-2"):
            with ui.column().classes("gap-1"):
                name_label = ui.label(system.name).classes("text-2xl font-bold")
                provider_label = None
                with ui.row().classes("items-center"):
                    ui.label(f"/{system.slug}").classes("text-gray-500")
                    status_badge = ui.badge(_STATUS_LABEL.get(system.status.value, system.status.value))
                    if system.kind == "deploy_only":
                        ui.badge("só implantação", color="grey").props("data-testid=system-kind-badge")
                    elif can_manage_system(user, system):
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

        # outside-arrows/mobile-arrows: em telas estreitas as 7 abas não cabem
        # e 3 delas (Checkpoints/Configurações/Auditoria) ficavam fora da
        # viewport sem nenhuma pista de que existiam mais abas — só rolagem
        # horizontal não-descoberta (achado do critique).
        if system.kind == "deploy_only":
            _render_deploy_only_tabs(system, user, name_label, breadcrumb_label)
            return

        with ui.tabs().classes("mx-4 w-full").props("outside-arrows mobile-arrows") as tabs:
            chat_tab = ui.tab("chat", label="Chat", icon="chat")
            editor_tab = ui.tab("editor", label="Editor", icon="code").props("data-testid=tab-editor")
            conn_tab = ui.tab("conn", label="Conexões", icon="storage")
            net_tab = ui.tab("net", label="Domínios", icon="public").props("data-testid=tab-domains")
            ckpt_tab = ui.tab("ckpt", label="Checkpoints", icon="history")
            repo_tab = ui.tab("repo", label="Repositório", icon="cloud_upload").props("data-testid=tab-repository")
            cfg_tab = ui.tab("cfg", label="Configurações", icon="settings")
            audit_tab = ui.tab("audit", label="Auditoria", icon="shield")

        with ui.tab_panels(tabs, value=chat_tab).classes("mx-4 w-full"):
            with ui.tab_panel(chat_tab):
                from .chat import render_chat

                # sessão e estado do Debug gravados na URL por _sync_url (ver chat.py)
                # — sobrevivem ao reload que trocar de tema força, que senão sempre
                # derrubava a sessão ativa e desligava o Debug no meio de uma
                # conversa (achados do critique)
                initial_session_id = ui.context.client.request.query_params.get("session")
                initial_debug_on = ui.context.client.request.query_params.get("debug") == "1"
                render_chat(system, user, initial_session_id, initial_debug_on)
            with ui.tab_panel(editor_tab):
                _render_editor(system, user)
            with ui.tab_panel(conn_tab):
                _render_connections(system, user)
            with ui.tab_panel(net_tab):
                _render_network(system, user)
            with ui.tab_panel(ckpt_tab):
                _render_checkpoints(system, user)
            with ui.tab_panel(repo_tab):
                _render_repository(system, user)
            with ui.tab_panel(cfg_tab):
                _render_configuration(system, user, name_label, breadcrumb_label, provider_label)
            with ui.tab_panel(audit_tab):
                _render_gate_history(system)
                _render_management_audit(system)
                _render_usage(system)


def _render_deploy_only_tabs(system, user, name_label, breadcrumb_label) -> None:
    """Sistema só implantação (change add-deploy-only-system, D9): sem Chat nem Checkpoints; a aba
    Implantação substitui a Repositório. O tipo do sistema não aparece como editável em lugar nenhum."""
    from .deploy_tab import render_deploy_tab

    with ui.tabs().classes("mx-4 w-full").props("outside-arrows mobile-arrows") as tabs:
        deploy_tab = ui.tab("deploy", label="Implantação", icon="rocket_launch").props("data-testid=tab-deploy")
        editor_tab = ui.tab("editor", label="Editor", icon="code").props("data-testid=tab-editor")
        conn_tab = ui.tab("conn", label="Conexões", icon="storage")
        net_tab = ui.tab("net", label="Domínios", icon="public").props("data-testid=tab-domains")
        cfg_tab = ui.tab("cfg", label="Configurações", icon="settings")
        audit_tab = ui.tab("audit", label="Auditoria", icon="shield")

    with ui.tab_panels(tabs, value=deploy_tab).classes("mx-4 w-full"):
        with ui.tab_panel(deploy_tab):
            render_deploy_tab(system, user)
        with ui.tab_panel(editor_tab):
            _render_editor(system, user)
        with ui.tab_panel(conn_tab):
            _render_connections(system, user)
        with ui.tab_panel(net_tab):
            _render_network(system, user)
        with ui.tab_panel(cfg_tab):
            _render_configuration(system, user, name_label, breadcrumb_label, None)
        with ui.tab_panel(audit_tab):
            _render_management_audit(system)


def _render_configuration(system, user, name_label, breadcrumb_label, provider_label) -> None:
    """Identidade (nome, provedor/modelo), rede de saída e ciclo de vida do
    sistema (specs system-management, https-forward-proxy). Num sistema só
    implantação não há agente nem broker: os textos falam da app e dos
    registros de pacote (change add-deploy-only-system, D2)."""
    deploy_only = system.kind == "deploy_only"
    if deploy_only:
        off_notice = "desabilitado — nenhum destino externo é liberado, nem os registros de pacote"
        internet_help = (
            "Desligado, o proxy de saída não libera nenhum destino externo, nem os registros de pacote: "
            "uma versão que muda o uv.lock não consegue ser implantada."
        )
        restricted_help = (
            "Ligado, substitui a allow-list padrão (registros de pacote) pela lista cadastrada na aba "
            "\"Domínios\" — só ela passa a valer. Para implantar uma versão que muda o uv.lock, inclua "
            "pypi.org e files.pythonhosted.org."
        )
    else:
        off_notice = "desabilitado — só o broker de inferência continua alcançável"
        internet_help = (
            "Desligado, o proxy de saída não libera nenhum destino externo; o broker de inferência "
            "(quando habilitado) não é afetado — ele nunca passa por este proxy."
        )
        restricted_help = (
            "Ligado, substitui a allow-list padrão (provedor de LLM/broker + registros de pacote) "
            "pela lista cadastrada na aba \"Domínios\" — só ela passa a valer."
        )
    ui.label("Rede de saída da app" if deploy_only else "Rede de saída do agente").classes("font-semibold mt-2")
    with ui.row().classes("items-center gap-6 mb-2"):
        with ui.column().classes("gap-0"):
            ui.switch(
                "Acesso à internet", value=system.internet_enabled,
                on_change=lambda e: (
                    network_policy.set_internet_enabled(system.id, e.value, author_id=user.id),
                    notify("Acesso à internet " + ("habilitado" if e.value else off_notice) + ".", kind="positive"),
                ),
            ).props("data-testid=toggle-internet-enabled")
            ui.label(internet_help).classes("text-xs text-gray-500")
        with ui.column().classes("gap-0"):
            ui.switch(
                "Modo restrito", value=system.restricted_network,
                on_change=lambda e: (
                    network_policy.set_restricted_network(system.id, e.value, author_id=user.id),
                    notify("Modo restrito " + ("ligado — só os domínios da aba \"Domínios\" são liberados." if e.value else "desligado — voltou a usar a allow-list padrão."), kind="positive"),
                ),
            ).props("data-testid=toggle-restricted-network")
            ui.label(restricted_help).classes("text-xs text-gray-500")

    with ui.row().classes("gap-2"):
        ui.button("Renomear sistema", icon="edit", on_click=lambda: open_rename_dialog()).props("dense outline data-testid=rename-system")
        if system.kind != "deploy_only":  # sem agente, sem provedor de LLM
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

    # ciclo de vida: arquivar (dono) e excluir definitivamente (admin, arquivado).
    # Moldura própria com rótulo: antes era só "mt-4" separando da edição de
    # nome/provedor acima — sem borda nem label, Arquivar e Revogar liam como
    # um par, mesmo agindo sobre coisas diferentes (sistema inteiro vs. só o
    # token de inferência desta sessão) — achado do critique. gap-4 (em vez
    # do gap-2 padrão) também distancia visualmente as duas ações entre si.
    with ui.card().classes("w-full mt-4").props("flat bordered"):
        ui.label("Zona de risco").classes("text-xs font-semibold text-gray-500")
        with ui.row().classes("gap-4 items-center"):

            def archive() -> None:
                from ..provisioning import archive_system

                archive_system(system, actor_id=user.id, actor_email=user.email)
                ui.navigate.to("/")

            ui.button("Arquivar sistema", icon="archive", on_click=archive).props("color=warning outline data-testid=archive-system")

            ui.button("Revogar acesso de inferência", icon="key_off", on_click=open_revoke_dialog).props("color=negative outline data-testid=revoke-access")

            if user.is_admin and system.status.value == "archived":

                def delete() -> None:
                    from ..provisioning import delete_system

                    delete_system(system, actor_id=user.id, actor_email=user.email)
                    ui.navigate.to("/")

                ui.button("Excluir definitivamente", icon="delete_forever", on_click=delete).props("color=negative data-testid=delete-system")


def _render_connections(system, user) -> None:
    """Conexões autorizadas para o sistema, na visão do dono (change add-db-manager-role, D10).

    Quem gere o catálogo autoriza; quem gerencia o sistema ativa, escolhendo alias e modo até o
    teto. Host, porta, banco e usuário não aparecem aqui (spec "Dados da conexão restritos a
    quem gere o catálogo")."""
    from .databases import MODE_LABELS, ddl_badge, kind_label, status_badge

    manage = can_manage_system(user, system)
    ui.label(
        "Bancos que um DB Manager autorizou para este sistema. Só as conexões ativas chegam ao "
        "agente e à app."
    ).classes("text-sm text-gray-600 mb-2 max-w-3xl")

    target: dict = {"grant": None}

    with ui.dialog() as activate_dialog, ui.card().classes("w-[28rem]"):
        activate_title = ui.label("").classes("font-semibold text-lg")
        alias = ui.input("Alias", on_change=lambda e: _preview()).classes("w-full").props(
            "data-testid=activate-alias"
        )
        env_preview = ui.label("").classes("text-xs text-gray-600 font-mono")
        ui.label(
            "O alias é o nome que o código e o agente usam. Não muda enquanto a conexão estiver ativa."
        ).classes("text-xs text-gray-600")
        activate_mode = ui.select({}, label="Modo de acesso").classes("w-full").props("data-testid=activate-mode")
        activate_feedback = ui.label("").classes("text-sm text-red-600")

        def _preview() -> None:
            key = connections.env_key(alias.value or "")
            env_preview.set_text(f"DATABASE_URL_{key}" if alias.value else "")

        def do_activate() -> None:
            try:
                connections.activate(system, target["grant"]["grant_id"], alias.value or "",
                                     activate_mode.value, actor=user)
            except (connections.InvalidAlias, connections.AliasTaken, connections.InvalidMode) as exc:
                activate_feedback.set_text(str(exc))
                return
            activate_dialog.close()
            notify("Conexão ativada. O agente e a app são reiniciados com o novo banco.", "positive")
            refresh_conns()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=activate_dialog.close).props("flat")
            ui.button("Ativar", icon="power", on_click=do_activate).props("data-testid=confirm-activate")

    def open_activate(c: dict) -> None:
        target["grant"] = c
        activate_title.set_text(f"Ativar {c['name']}")
        alias.set_value(c["suggested_alias"])
        _preview()
        options = {m: MODE_LABELS[m] for m in c["modes"]}
        default = c["mode"] if c["mode"] in options else c["modes"][-1]
        activate_mode.set_options(options, value=default)
        activate_feedback.set_text("")
        activate_dialog.open()

    with ui.dialog() as mode_dialog, ui.card().classes("w-96"):
        mode_title = ui.label("").classes("font-semibold text-lg")
        mode_select = ui.select({}, label="Modo de acesso").classes("w-full").props("data-testid=change-mode")
        ui.label("Mudar o modo reinicia o agente e a app do sistema.").classes("text-xs text-gray-600")

        def do_mode() -> None:
            try:
                connections.set_mode(system, target["grant"]["grant_id"], mode_select.value, actor=user)
            except connections.InvalidMode as exc:
                notify(str(exc), "negative")
                return
            mode_dialog.close()
            refresh_conns()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=mode_dialog.close).props("flat")
            ui.button("Salvar", icon="save", on_click=do_mode).props("data-testid=confirm-change-mode")

    def open_mode(c: dict) -> None:
        target["grant"] = c
        mode_title.set_text(f"Modo de {c['alias']}")
        mode_select.set_options({m: MODE_LABELS[m] for m in c["modes"]}, value=c["mode"])
        mode_dialog.open()

    with ui.dialog() as off_dialog, ui.card().classes("w-96"):
        off_message = ui.label("").classes("text-sm")

        def do_deactivate() -> None:
            connections.deactivate(system, target["grant"]["grant_id"], actor=user)
            off_dialog.close()
            refresh_conns()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=off_dialog.close).props("flat")
            ui.button("Desativar", icon="power_off", on_click=do_deactivate).props(
                "color=warning data-testid=confirm-deactivate"
            )

    def ask_deactivate(c: dict) -> None:
        target["grant"] = c
        off_message.set_text(
            f"Desativar {c['alias']}? O agente e a app deixam de acessar este banco; "
            f"DATABASE_URL_{connections.env_key(c['alias'])} some do ambiente da app."
        )
        off_dialog.open()

    notices_box = ui.column().classes("w-full max-w-3xl gap-2")
    conns_box = ui.column().classes("w-full max-w-3xl gap-3")

    _NOTICE_TEXT = {
        "revoked": "foi revogada por um DB Manager",
        "ceiling_lowered": "teve o modo de acesso reduzido por um DB Manager",
        "connection_deleted": "foi excluída do catálogo",
        "migration_conflict": "ficou inativa na migração para o catálogo",
    }

    def dismiss(notice_id: str) -> None:
        connections.dismiss_notice(system, notice_id, actor=user)
        refresh_conns()

    def refresh_conns() -> None:
        notices_box.clear()
        with notices_box:
            for n in connections.list_notices(system.id):
                with ui.card().classes("w-full").props(f"data-testid=conn-notice:{n['kind']}"):
                    with ui.row().classes("w-full items-start gap-2 no-wrap"):
                        ui.icon("warning").classes("text-amber-700 mt-1")
                        with ui.column().classes("gap-0 grow"):
                            label = n["alias"] or n["connection_name"]
                            ui.label(f"A conexão {label} {_NOTICE_TEXT.get(n['kind'], 'mudou')}").classes(
                                "text-sm font-medium"
                            )
                            who = n["actor_email"] or "o portal"
                            ui.label(f"{n['detail']} · {who} · {_stamp(n['created_at'])}").classes(
                                "text-xs text-gray-600"
                            )
                        if manage:
                            ui.button("Dispensar", on_click=lambda n=n: dismiss(n["id"])).props(
                                "dense flat data-testid=conn-notice-dismiss"
                            )
        conns_box.clear()
        conns = connections.list_system_connections(system.id)
        with conns_box:
            if not conns:
                ui.label(
                    "Nenhum banco autorizado para este sistema. Peça a um DB Manager que autorize o "
                    "banco de que você precisa."
                ).classes("text-gray-500 text-sm").props("data-testid=conn-empty")
            for c in conns:
                with ui.card().classes("w-full").props(f"data-testid=conn-card:{c['name']}"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.label(c["alias"] if c["active"] else c["name"]).classes("font-semibold")
                        kind_label(c["kind"])
                        status_badge(c["status"])
                        if c["active"]:
                            ui.badge(MODE_LABELS[c["mode"]]).props("color=primary data-testid=conn-mode-badge")
                        else:
                            ui.badge("inativa").props(
                                "color=neutral text-color=neutraltext data-testid=conn-inactive-badge"
                            )
                        ddl_badge(c["schema_admin_since"])
                    if c["active"]:
                        ui.label(f"{c['name']} · DATABASE_URL_{connections.env_key(c['alias'])}").classes(
                            "text-xs text-gray-600 font-mono"
                        )
                    if c["description"]:
                        ui.label(c["description"]).classes("text-sm text-gray-600")
                    ui.label(f"Teto autorizado: {MODE_LABELS[c['max_mode']]}").classes("text-xs text-gray-600")
                    if not manage:
                        continue
                    with ui.row().classes("gap-2"):
                        if c["active"]:
                            if len(c["modes"]) > 1:
                                ui.button("Mudar modo", icon="tune", on_click=lambda c=c: open_mode(c)).props(
                                    "dense outline data-testid=conn-change-mode"
                                )
                            ui.button("Desativar", icon="power_off", on_click=lambda c=c: ask_deactivate(c)).props(
                                "dense outline color=warning data-testid=conn-deactivate"
                            )
                        else:
                            ui.button("Ativar", icon="power", on_click=lambda c=c: open_activate(c)).props(
                                "dense data-testid=conn-activate"
                            )

    refresh_conns()


def _render_network(system, user) -> None:
    """Lista de domínios do modo restrito do proxy HTTP(S) de saída (change
    `agent-https-forward-proxy`, D7/D8) — mesmo nível de acesso da aba
    Conexões: quem gerencia o sistema cadastra os domínios dele. Só tem
    efeito quando "Modo restrito" está ligado (aba Configurações), mas a
    lista pode ser editada com o modo desligado também."""
    manage = can_manage_system(user, system)
    default_list = (
        "registros de pacote" if system.kind == "deploy_only" else "provedor de LLM/broker + registros de pacote"
    )
    ui.label(
        "Domínios liberados quando o \"Modo restrito\" está ligado (aba Configurações) — "
        f"substituem por completo a allow-list padrão ({default_list})."
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
                        # outline, não flat: todo outro "remover item da lista"
                        # do portal (Conexões, chaves de provedor, grupos) usa
                        # outline — aqui era a única exceção, um ícone vermelho
                        # solto sem moldura de botão nenhuma (achado do critique).
                        ui.button(
                            icon="delete", on_click=lambda d=d: remove_domain(d["id"])
                        ).props("dense outline color=negative data-testid=domain-remove")

    def remove_domain(domain_id: str) -> None:
        network_policy.remove_allowed_domain(system.id, domain_id, author_id=user.id)
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
                ui.label(workspace_files.display_path(rel_path)).classes("text-sm font-medium")
                if content.language:
                    ui.badge(content.language, color="grey-6").props("data-testid=editor-file-language")
            ui.codemirror(content.text or "", language=content.language, theme=cm_theme).props("data-testid=editor-content").classes("w-full h-full").disable()

    def select_file(e) -> None:
        # clicar no nome de uma pasta abre ou fecha a pasta, em vez de "selecionar" algo que
        # não tem conteúdo (antes, só a setinha abria)
        if e.value in state.get("folders", set()):
            tree = state["tree"]
            if e.value in (tree._props.get("expanded") or []):
                tree.collapse([e.value])
            else:
                tree.expand([e.value])
            tree.deselect()
            return
        state["selected"] = e.value
        render_content()

    def _folder_ids(nodes: list[dict]) -> set[str]:
        ids: set[str] = set()
        for node in nodes:
            if node.get("children"):
                ids.add(node["id"])
                ids |= _folder_ids(node["children"])
        return ids

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
            state["folders"] = _folder_ids(nodes)
            state["tree"] = ui.tree(nodes, on_select=select_file).props("data-testid=editor-tree")

    refresh_tree()
    render_content()
    ui.timer(2.0, refresh_tree)


# Rótulo e ícone por origem do checkpoint (coluna `checkpoints.origin`).
_CHECKPOINT_ORIGINS = {
    "run": ("execução do agente", "smart_toy"),
    "manual": ("criado manualmente", "commit"),
    "restore": ("restauração", "restore"),
}


def _render_checkpoints(system, user) -> None:
    from .. import checkpoints as cp_service

    ui.label("Pontos salvos do código da app — restaure ou exclua").classes("text-sm text-gray-500 mb-2")

    def create_checkpoint() -> None:
        # record_checkpoint devolve None quando o git não tem nada para commitar;
        # sem aviso o botão parece quebrado.
        try:
            cp = cp_service.record_checkpoint(
                system, None, "checkpoint manual", author=user, origin=cp_service.ORIGIN_MANUAL,
            )
        except cp_service.MergeIncomplete as exc:
            notify(f"Checkpoint não criado: {exc}", "warning")
            return
        if cp is None:
            notify("Nada mudou no workspace desde o último checkpoint.", "info")
            return
        notify(f"Checkpoint {cp.git_sha[:8]} criado.", "positive")
        refresh_cps()
        from .. import git_sync

        git_sync.after_checkpoint(system, user)

    # mesmo peso de "Nova conexão"/"Adicionar" (as outras duas ações
    # primárias de "criar algo nesta aba") — "outline dense" ficava bem
    # mais quieto que as duas, três abas antes/depois (achado do critique).
    ui.button("Criar checkpoint agora", icon="add", on_click=create_checkpoint)
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
                        # a restauração vira um checkpoint novo e não apaga os posteriores
                        # (change isolate-workspace-repository)
                        restored = cp_service.rollback(system, sha, author=user)
                        if restored is None:
                            notify(f"Nada a restaurar: o workspace já está no checkpoint {sha[:8]}.", "info")
                            return
                        notify(f"workspace restaurado para {sha[:8]} (checkpoint {restored.git_sha[:8]})", "positive")
                        refresh_cps()
                        from .. import git_sync

                        git_sync.after_checkpoint(system, user)

                    origin_label, origin_icon = _CHECKPOINT_ORIGINS.get(cp.get("origin"), _CHECKPOINT_ORIGINS["run"])
                    with ui.timeline_entry(
                        title=cp["git_sha"][:8], subtitle=f"{_stamp(cp['created_at'])} · {origin_label}", icon=origin_icon,
                    ).props(f"data-testid=checkpoint-entry:{cp.get('origin', 'run')}"):
                        ui.label(cp["message"][:140]).classes("text-sm")
                        with ui.row().classes("gap-2"):
                            ui.button("Restaurar", icon="restore", on_click=do_rollback).props("dense outline")
                            ui.button("Excluir", icon="delete", on_click=lambda cp=cp: ask_delete(cp)).props("dense outline color=negative data-testid=checkpoint-delete")

    refresh_cps()
    ui.timer(2.0, refresh_cps)


# Estado do vínculo com o repositório remoto, como aparece para o editor.
_REPO_STATES = {
    "synced": ("sincronizado", "positive"),
    "pending": ("envio pendente", "warning"),
    "diverged": ("divergente", "negative"),
    "error": ("erro", "negative"),
}


def _render_repository(system, user) -> None:
    """Aba Repositório (change add-system-git-remote): vínculo do sistema com um repositório git
    remoto. Chave privada e token nunca aparecem aqui; só a chave pública e o fato de haver token."""
    from nicegui import run as _run

    from .. import git_sync
    from ..services import git_remote

    ui.label(
        "Envia os checkpoints deste sistema para uma branch de trabalho num repositório GitLab, "
        "de onde a promoção segue por merge request."
    ).classes("text-sm text-gray-500 mb-2")

    view = git_remote.ensure_remote(system, user)
    state: dict = {"pending_host": None}

    def _error(exc: Exception) -> None:
        notify(str(exc), "negative")

    # --- chave de implantação ---------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl"):
        ui.label("Chave de implantação").classes("font-semibold")
        ui.label(
            "Cadastre esta chave pública no projeto do GitLab (Configurações > Repositório > Chaves "
            "de implantação), com permissão de escrita, por alguém que pode enviar à branch de trabalho."
        ).classes("text-sm text-gray-500")
        key_area = ui.textarea(value=view["public_key"]).props("readonly outlined autogrow data-testid=repo-public-key").classes("w-full font-mono text-xs")
        fp_label = ui.label(f"Impressão digital: {view['fingerprint']}").classes("text-xs text-gray-500 font-mono")
        with ui.row().classes("gap-2"):
            ui.button("Copiar chave", icon="content_copy",
                      on_click=lambda: (ui.clipboard.write(key_area.value), notify("Chave pública copiada.", "info"))
                      ).props("outline data-testid=repo-copy-key")

            with ui.dialog() as rotate_dialog, ui.card().classes("w-96"):
                ui.label("Gerar nova chave").classes("font-semibold text-lg")
                ui.label("A chave atual deixa de ser usada. Cadastre a nova no GitLab antes do próximo envio.").classes("text-sm")

                def do_rotate() -> None:
                    new = git_remote.rotate_key(system, user)
                    key_area.set_value(new["public_key"])
                    fp_label.set_text(f"Impressão digital: {new['fingerprint']}")
                    rotate_dialog.close()
                    notify("Nova chave gerada.", "positive")

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Cancelar", on_click=rotate_dialog.close).props("flat")
                    ui.button("Gerar", on_click=do_rotate).props("color=warning data-testid=repo-rotate-confirm")
            ui.button("Gerar nova chave", icon="autorenew", on_click=rotate_dialog.open).props("outline data-testid=repo-rotate-key")

    # --- endereço e branches ----------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Repositório").classes("font-semibold")
        url_input = ui.input("Endereço SSH do repositório", value=view["url"],
                             placeholder="git@gitlab.exemplo.com:time/app.git").classes("w-full").props("data-testid=repo-url")
        with ui.row().classes("w-full gap-2"):
            working_input = ui.input("Branch de trabalho", value=view["working_branch"]).classes("w-56").props("data-testid=repo-working-branch")
            target_input = ui.input("Branch de destino", value=view["target_branch"]).classes("w-56").props("data-testid=repo-target-branch")
        api_input = ui.input("Endereço da API do GitLab (opcional)", value=view["api_url"],
                             placeholder="derivado do endereço: https://<host>").classes("w-full").props("data-testid=repo-api-url")

        def save() -> None:
            try:
                git_remote.configure(system, user, url=url_input.value, working_branch=working_input.value,
                                     target_branch=target_input.value, api_url=api_input.value)
            except (git_remote.InvalidRemote, git_remote.NotPermitted) as exc:
                _error(exc)
                return
            notify("Repositório salvo. Teste a conexão para confirmar o servidor.", "positive")
            refresh()

        ui.button("Salvar", icon="save", on_click=save).props("data-testid=repo-save")

    # --- conexão, identidade do servidor e ativação -----------------------------------------
    with ui.dialog() as host_dialog, ui.card().classes("w-[32rem]"):
        ui.label("Confirmar o servidor").classes("font-semibold text-lg")
        ui.label("Confira se a impressão digital abaixo é a do seu GitLab antes de continuar.").classes("text-sm")
        host_fp = ui.label("").classes("font-mono text-xs").props("data-testid=repo-host-fingerprint")

        async def confirm_host() -> None:
            git_remote.confirm_host_key(system, user, state["pending_host"])
            host_dialog.close()
            await _check_access()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=host_dialog.close).props("flat")
            ui.button("Confirmar", on_click=confirm_host).props("data-testid=repo-confirm-host")

    async def _check_access() -> None:
        secrets = git_remote.load_secrets(system.id)
        try:
            branches = await _run.io_bound(git_sync.check_access, system.slug, secrets)
        except git_sync.RemoteError as exc:
            _error(exc)
            return
        notify("Conexão válida. Branches no remoto: " + (", ".join(branches) or "nenhuma"), "positive")
        refresh()

    async def test_connection() -> None:
        current = git_remote.get_view(system)
        if not current or not current["url"]:
            notify("Salve o endereço do repositório antes de testar.", "warning")
            return
        try:
            scanned = await _run.io_bound(git_sync.scan_host_key, git_remote.parse_remote_url(current["url"]))
        except git_sync.RemoteError as exc:
            _error(exc)
            return
        secrets = git_remote.load_secrets(system.id)
        if secrets.host_key and set(secrets.host_key.splitlines()) & set(scanned.key.splitlines()):
            await _check_access()
            return
        state["pending_host"] = scanned.key
        host_fp.set_text("\n".join(scanned.fingerprints))
        host_dialog.open()

    async def activate() -> None:
        try:
            await _run.io_bound(git_sync.activate, system, user)
        except (git_remote.InvalidRemote, git_remote.NotPermitted, git_sync.RemoteError) as exc:
            _error(exc)
            return
        notify("Vínculo ativado.", "positive")
        refresh()

    def deactivate() -> None:
        git_remote.set_enabled(system, user, False)
        notify("Vínculo desativado. Nada foi alterado no remoto.", "info")
        refresh()

    async def push_now() -> None:
        result = await _run.io_bound(git_sync.push_now, system, user)
        if result and result.get("error"):
            notify(result["error"], "warning")
        elif result and result.get("sent"):
            notify(f"Enviado: {result['sent'][:8]}", "positive")
        else:
            notify("Nada a enviar.", "info")
        refresh()

    async def _guarded(fn, *args, ok: str) -> None:
        try:
            await _run.io_bound(fn, *args)
        except (git_remote.InvalidRemote, git_remote.NotPermitted, git_sync.RemoteError) as exc:
            _error(exc)
            refresh()
            return
        notify(ok, "positive")
        refresh()

    async def sync_now() -> None:
        try:
            result = await _run.io_bound(git_sync.sync_now, system, user)
        except git_sync.UnsavedChanges as exc:
            notify(str(exc), "warning")
            refresh()
            return
        except (git_remote.InvalidRemote, git_sync.RemoteError) as exc:
            _error(exc)
            refresh()
            return
        notify("Alterações do remoto trazidas para o workspace." if result.get("integrated")
               else "Nada novo no remoto.", "positive" if result.get("integrated") else "info")
        refresh()

    # --- token de API -------------------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Token de API do GitLab (opcional)").classes("font-semibold")
        ui.label(
            "Usado só para abrir o merge request de promoção. Recomendado: token de projeto com papel "
            "Developer e escopo api. Sem token, a promoção mostra o link de criação."
        ).classes("text-sm text-gray-500")
        token_status = ui.label("").classes("text-sm").props("data-testid=repo-token-status")
        with ui.row().classes("items-center gap-2"):
            token_input = ui.input("Token", password=True, password_toggle_button=False).classes("w-80").props("data-testid=repo-token")

            def save_token() -> None:
                try:
                    git_remote.set_api_token(system, user, token_input.value)
                except git_remote.InvalidRemote as exc:
                    _error(exc)
                    return
                token_input.set_value("")
                notify("Token cadastrado.", "positive")
                refresh()

            def remove_token() -> None:
                try:
                    git_remote.remove_api_token(system, user)
                except git_remote.InvalidRemote as exc:
                    _error(exc)
                    return
                notify("Token removido.", "info")
                refresh()

            ui.button("Salvar token", on_click=save_token).props("data-testid=repo-token-save")

            async def test_token() -> None:
                try:
                    message = await _run.io_bound(git_sync.check_api_token, system)
                except git_sync.RemoteError as exc:
                    _error(exc)
                    return
                notify(message, "positive")

            test_token_btn = ui.button("Testar token", on_click=test_token).props("outline data-testid=repo-token-test")
            remove_token_btn = ui.button("Remover", on_click=remove_token).props("outline color=negative data-testid=repo-token-remove")

    # --- estado ------------------------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Estado").classes("font-semibold")
        with ui.row().classes("items-center gap-2"):
            state_badge = ui.badge("").props("data-testid=repo-state")
            state_detail = ui.label("").classes("text-sm").props("data-testid=repo-state-detail")
        last_sent = ui.label("").classes("text-xs text-gray-500 font-mono").props("data-testid=repo-last-sent")
        with ui.row().classes("gap-2 mt-1"):
            ui.button("Testar conexão", icon="lan", on_click=test_connection).props("outline data-testid=repo-test")
            enable_btn = ui.button("Ativar vínculo", icon="link", on_click=activate).props("data-testid=repo-enable")
            disable_btn = ui.button("Desativar vínculo", icon="link_off", on_click=deactivate).props("outline data-testid=repo-disable")
            push_btn = ui.button("Enviar agora", icon="upload", on_click=push_now).props("outline data-testid=repo-push-now")
            sync_btn = ui.button("Sincronizar agora", icon="sync", on_click=lambda: sync_now()).props("outline data-testid=repo-sync-now")

    # --- promoção (design D7) ----------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2") as promote_card:
        ui.label("Promoção").classes("font-semibold")
        ui.label("Abre (ou mostra) o merge request da branch de trabalho para a de destino, onde a revisão "
                 "e os pipelines acontecem. Nada é aberto sem esta ação.").classes("text-sm text-gray-500")

        async def request_promotion() -> None:
            try:
                result = await _run.io_bound(git_sync.request_promotion, system, user)
            except (git_remote.InvalidRemote, git_remote.NotPermitted, git_sync.RemoteError) as exc:
                _error(exc)
                return
            mr_link.set_text(result["url"])
            mr_link.props(f"href={result['url']}")
            mr_link.set_visibility(True)
            notify(result["message"], "warning" if result["fallback"] else "positive")

        ui.button("Solicitar promoção", icon="merge_type", on_click=request_promotion).props("data-testid=repo-promote")
        mr_link = ui.link("", "#", new_tab=True).classes("text-sm font-mono break-all").props("data-testid=repo-mr-url")
        mr_link.set_visibility(False)

    # --- alterações não salvas (design D4) ---------------------------------------------------
    with ui.dialog() as discard_dialog, ui.card().classes("w-96"):
        ui.label("Descartar alterações não salvas").classes("font-semibold text-lg")
        ui.label("O workspace volta ao último checkpoint. As alterações sem checkpoint são perdidas.").classes("text-sm")

        async def confirm_discard() -> None:
            discard_dialog.close()
            await _guarded(git_sync.discard_unsaved, system, user, ok="Alterações descartadas e repositório sincronizado.")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=discard_dialog.close).props("flat")
            ui.button("Descartar", on_click=confirm_discard).props("color=negative data-testid=repo-discard-confirm")

    unsaved_card = ui.card().classes("w-full max-w-3xl mt-2").props("data-testid=repo-unsaved")
    with unsaved_card:
        ui.label("Alterações não salvas").classes("font-semibold")
        ui.label(
            "O repositório remoto tem alterações novas e o workspace tem alterações sem checkpoint. "
            "O agente só volta a executar depois que você decidir o que fazer com elas."
        ).classes("text-sm")
        with ui.row().classes("gap-2"):
            ui.button("Salvar como checkpoint", icon="save",
                      on_click=lambda: _guarded(git_sync.save_unsaved, system, user, ok="Alterações salvas e repositório sincronizado.")
                      ).props("data-testid=repo-save-unsaved")
            ui.button("Descartar alterações não salvas", icon="delete_sweep", on_click=discard_dialog.open
                      ).props("outline color=negative data-testid=repo-discard-unsaved")

    # --- divergência (design D5) -------------------------------------------------------------
    with ui.dialog() as adopt_dialog, ui.card().classes("w-[32rem]"):
        ui.label("Adotar a versão do remoto").classes("font-semibold text-lg")
        ui.label("O workspace passa a ter o conteúdo da branch remota. Estes checkpoints locais, não enviados, "
                 "ficam de lado (continuam restauráveis na aba Checkpoints):").classes("text-sm")
        adopt_list = ui.column().classes("gap-0").props("data-testid=repo-adopt-list")

        async def confirm_adopt() -> None:
            adopt_dialog.close()
            await _guarded(git_sync.adopt_remote, system, user, ok="Versão do remoto adotada.")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=adopt_dialog.close).props("flat")
            ui.button("Adotar", on_click=confirm_adopt).props("color=warning data-testid=repo-adopt-confirm")

    def open_adopt() -> None:
        adopt_list.clear()
        with adopt_list:
            pending = git_sync.unsent_checkpoints(system)
            if not pending:
                ui.label("(nenhum)").classes("text-sm text-gray-500")
            for cp in pending:
                ui.label(f"{cp['git_sha'][:8]} — {cp['message'][:80]}").classes("text-sm font-mono")
        adopt_dialog.open()

    diverged_card = ui.card().classes("w-full max-w-3xl mt-2").props("data-testid=repo-diverged")
    with diverged_card:
        ui.label("Divergência com o repositório remoto").classes("font-semibold")
        diverged_text = ui.label("").classes("text-sm")
        conflict_list = ui.label("").classes("text-sm font-mono").props("data-testid=repo-conflict-files")
        with ui.row().classes("gap-2"):
            resolve_btn = ui.button("Resolver no workspace", icon="merge",
                                    on_click=lambda: _guarded(git_sync.resolve_in_workspace, system, user,
                                                              ok="Conflito levado ao workspace: peça ao agente para resolver os arquivos marcados.")
                                    ).props("data-testid=repo-resolve")
            cancel_resolve_btn = ui.button("Cancelar resolução", icon="undo",
                                           on_click=lambda: _guarded(git_sync.cancel_resolution, system, user,
                                                                     ok="Resolução cancelada.")
                                           ).props("outline data-testid=repo-cancel-resolve")
            ui.button("Adotar a versão do remoto", icon="cloud_download", on_click=open_adopt
                      ).props("outline color=warning data-testid=repo-adopt")

    def refresh() -> None:
        current = git_remote.get_view(system)
        if current is None:
            return
        token_status.set_text("Token configurado." if current["has_api_token"] else "Nenhum token configurado.")
        remove_token_btn.set_visibility(current["has_api_token"])
        test_token_btn.set_visibility(current["has_api_token"])
        promote_card.set_visibility(current["enabled"])
        if not current["enabled"]:
            state_badge.set_text("desativado")
            state_badge.props("color=grey")
            state_detail.set_text("" if current["url"] else "Configure o endereço do repositório.")
        else:
            label, color = _REPO_STATES.get(current["state"], (current["state"], "grey"))
            state_badge.set_text(label)
            state_badge.props(f"color={color}")
            state_detail.set_text(current["state_detail"])
        last_sent.set_text(f"Último commit enviado: {current['last_pushed_sha'][:12]}" if current["last_pushed_sha"] else "")
        enable_btn.set_visibility(not current["enabled"] and bool(current["url"]))
        disable_btn.set_visibility(current["enabled"])
        push_btn.set_visibility(current["enabled"] and current["state"] in ("pending", "error"))
        sync_btn.set_visibility(current["enabled"] and current["state"] != "diverged")
        unsaved_card.set_visibility(current["enabled"] and current["unsaved_blocked"])
        diverged = current["enabled"] and current["state"] == "diverged"
        diverged_card.set_visibility(diverged)
        if diverged:
            conflict_list.set_text("Arquivos em conflito: " + ", ".join(current["conflict_files"]))
            diverged_text.set_text(
                "Resolução em andamento: os arquivos estão com marcas de conflito. O próximo checkpoint "
                "sem marcas conclui a integração." if current["merge_in_progress"] else
                "O remoto e o sistema alteraram os mesmos trechos. Os envios estão suspensos; o chat continua disponível."
            )
            resolve_btn.set_visibility(not current["merge_in_progress"])
            cancel_resolve_btn.set_visibility(current["merge_in_progress"])

    refresh()
    ui.timer(3.0, refresh)


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
                color = {"bloqueada": "text-red-600", "recusada": "text-orange-600", "aprovada": "text-green-700",
                         "liberada": "text-amber-700"}.get(d["decision"], "")
                autor = d["author_email"] or "sistema"
                tag = "liberada (schema_admin)" if d["decision"] == "liberada" else d["decision"]
                with ui.row().classes("w-full items-center").props(f"data-testid=gate-decision:{d['decision']}"):
                    ui.label(f"[{tag}] {d['sql'][:70]}").classes(f"text-sm {color}")
                    ui.label(f"({d['origin']} · autor: {autor} · {_stamp(d['created_at'])})").classes("text-xs text-gray-500")

    refresh_gate()
    ui.timer(2.0, refresh_gate)
