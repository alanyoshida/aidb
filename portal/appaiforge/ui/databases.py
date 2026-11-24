"""Bancos de dados: catálogo de conexões e autorizações por sistema (change add-db-manager-role,
design D10; specs db-connections, db-connection-access). Só DB Managers e admins."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nicegui import ui

from ..rbac import can_manage_catalog
from ..services import connections
from .common import get_current_user, notify, redirect_to_login, render_header

KIND_OPTIONS = {"postgres": "PostgreSQL", "mysql": "MySQL", "bigquery": "BigQuery"}
KIND_DEFAULT_PORT = {"postgres": 5432, "mysql": 3306, "bigquery": 0}
STATUS_COLOR = {"healthy": "positive", "degraded": "negative", "unknown": "neutral"}
STATUS_LABEL = {"healthy": "saudável", "degraded": "degradada", "unknown": "não verificada"}
MODE_LABELS = connections.MODE_LABELS


def date_label(iso: str | None) -> str:
    """`dd/mm/aaaa` no fuso de exibição."""
    from ..config import get_settings

    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        dt = dt.astimezone(ZoneInfo(get_settings().display_timezone))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return ""
    return dt.strftime("%d/%m/%Y")


def status_badge(status: str) -> None:
    color = STATUS_COLOR.get(status, "neutral")
    # só o neutro precisa de texto próprio; os coloridos já vêm com o par "on-" do tema
    extra = " text-color=neutraltext" if color == "neutral" else ""
    ui.badge(STATUS_LABEL.get(status, status)).props(f"color={color}{extra} data-testid=conn-status-badge")


def kind_label(kind: str) -> None:
    ui.label(KIND_OPTIONS.get(kind, kind)).classes("text-xs text-gray-600")


def ddl_badge(since_iso: str | None) -> None:
    if since_iso:
        ui.badge(f"DDL liberada desde {date_label(since_iso)}").props("color=warning data-testid=ddl-since")


class ConfirmDialog:
    """Confirmação com lista opcional de sistemas afetados (exclusão, revogação, schema_admin)."""

    def __init__(self) -> None:
        self._action = None
        self._on_cancel = None
        # persistente: só os botões fecham, para o cancelamento sempre desfazer o que a tela mostra
        with ui.dialog().props("persistent") as self.dialog, ui.card().classes("w-[28rem]"):
            self.title = ui.label("").classes("font-semibold text-lg")
            self.message = ui.label("").classes("text-sm")
            self.systems = ui.column().classes("gap-0 text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=self._cancel).props("flat data-testid=cancel-action")
                self.confirm = ui.button("Confirmar", on_click=self._run).props("data-testid=confirm-action")

    def ask(self, title: str, message: str, confirm_label: str, action, systems: list[dict] | None = None,
            negative: bool = True, on_cancel=None) -> None:
        self.title.set_text(title)
        self.message.set_text(message)
        self.systems.clear()
        with self.systems:
            for item in systems or []:
                ui.label(f"• {item.get('name') or item.get('system_name')} ({item['slug']})").classes("text-gray-600")
        self.confirm.set_text(confirm_label)
        self.confirm.props(f"color={'negative' if negative else 'warning'}")
        self._action = action
        self._on_cancel = on_cancel
        self.dialog.open()

    def _cancel(self) -> None:
        self.dialog.close()
        if self._on_cancel is not None:
            self._on_cancel()

    def _run(self) -> None:
        self.dialog.close()
        if self._action is not None:
            self._action()


def register() -> None:
    @ui.page("/databases")
    def databases_page() -> None:
        user = get_current_user()
        if user is None:
            redirect_to_login()
            return
        render_header(user)
        if not can_manage_catalog(user):
            ui.label("Permissão insuficiente.").classes("text-red-600 text-lg m-8").props(
                "data-testid=databases-forbidden"
            )
            return
        ui.label("Bancos de dados").classes("text-2xl font-bold m-4")
        with ui.tabs().classes("w-full").props("align=left") as tabs:
            catalog_tab = ui.tab("Catálogo", icon="storage")
            health_tab = ui.tab("Conexões degradadas", icon="warning").props("data-testid=tab-degraded")
        with ui.tab_panels(tabs, value=catalog_tab).classes("w-full"):
            with ui.tab_panel(catalog_tab):
                _catalog_panel(user)
            with ui.tab_panel(health_tab):
                _degraded_panel()


def _catalog_panel(user) -> None:
    ui.label(
        "Conexões que você pode autorizar para sistemas. O dono do sistema escolhe se ativa cada "
        "uma, com alias e modo até o teto que você definir."
    ).classes("text-sm text-gray-600 mb-3 max-w-3xl")
    confirm = ConfirmDialog()
    form = _ConnectionForm(on_saved=lambda: refresh())
    systems_cache: dict = {"options": {}}
    # Autorizações abertas sobrevivem ao redesenho: sem isto, autorizar, mudar o teto ou revogar
    # fechava o painel em que a pessoa estava trabalhando.
    open_grants: set[str] = set()

    def track_open(conn_id: str, is_open: bool) -> None:
        if is_open:
            open_grants.add(conn_id)
        else:
            open_grants.discard(conn_id)

    def system_options() -> dict:
        systems_cache["options"] = {
            s["id"]: f"{s['name']} ({s['slug']}) · {s['owner_email']}" for s in connections.list_systems_for_grant()
        }
        return systems_cache["options"]

    ui.button("Nova conexão", icon="add", on_click=form.open_new).classes("mb-3").props(
        "data-testid=new-catalog-connection"
    )
    box = ui.column().classes("w-full max-w-4xl gap-3")

    def ask_delete(c: dict) -> None:
        affected = connections.connection_systems(c["id"])

        def do_delete() -> None:
            result = connections.delete_connection(c["id"], actor=user, confirmed=True)
            if result["rotate_key"]:
                notify("Conexão excluída. A chave da Service Account já entregue só deixa de valer "
                       "quando for rotacionada no GCP.", "warning")
            else:
                notify("Conexão excluída.", "positive")
            refresh()

        message = (
            f"Excluir '{c['name']}' do catálogo? Os sistemas abaixo perdem o acesso na hora."
            if affected else f"Excluir '{c['name']}' do catálogo?"
        )
        confirm.ask("Excluir conexão", message, "Excluir", do_delete, affected)

    def apply_ceiling(c: dict, grant: dict, new_mode: str) -> None:
        def do_set(confirmed: bool = False) -> None:
            try:
                result = connections.set_ceiling(grant["grant_id"], new_mode, actor=user, confirmed=confirmed)
            except connections.NeedsConfirmation as exc:
                confirm.ask(
                    "Liberar DDL numa conexão compartilhada",
                    "Esta conexão também está autorizada para os sistemas abaixo. Uma alteração de "
                    "schema feita por este sistema pode afetá-los.",
                    "Liberar mesmo assim", lambda: do_set(True), exc.systems, negative=False,
                    on_cancel=refresh,
                )
                return
            except connections.InvalidMode as exc:
                notify(str(exc), "negative")
                refresh()
                return
            if result["mode_lowered"]:
                notify("Teto rebaixado; o modo do sistema caiu junto e o dono foi avisado.", "warning")
            refresh()

        do_set()

    def ask_revoke(c: dict, grant: dict) -> None:
        def do_revoke() -> None:
            result = connections.revoke_grant(grant["grant_id"], actor=user)
            if result["rotate_key"]:
                notify("Autorização revogada. A chave da Service Account já entregue só deixa de "
                       "valer quando for rotacionada no GCP.", "warning")
            else:
                notify("Autorização revogada.", "positive")
            refresh()

        detail = (
            f"O sistema perde o acesso a '{c['name']}' na hora; o agente e a app são reiniciados."
            if grant["active"] else f"'{c['name']}' deixa de estar disponível para o sistema."
        )
        confirm.ask(f"Revogar de {grant['system_name']}", detail, "Revogar", do_revoke)

    def grant(c: dict, system_id: str | None, max_mode: str) -> None:
        if not system_id:
            notify("Escolha o sistema.", "warning")
            return

        def do_grant(confirmed: bool = False) -> None:
            try:
                connections.grant_connection(c["id"], system_id, max_mode, actor=user, confirmed=confirmed)
            except connections.NeedsConfirmation as exc:
                confirm.ask(
                    "Liberar DDL numa conexão compartilhada",
                    "Esta conexão também está autorizada para os sistemas abaixo. Uma alteração de "
                    "schema feita por este sistema pode afetá-los.",
                    "Autorizar mesmo assim", lambda: do_grant(True), exc.systems, negative=False,
                )
                return
            except (connections.GrantExists, connections.InvalidMode) as exc:
                notify(str(exc), "negative")
                return
            notify("Autorizado. O dono do sistema já pode ativar a conexão.", "positive")
            refresh()

        do_grant()

    def render_grants(c: dict) -> None:
        grants = connections.list_grants(c["id"])
        modes = {m: MODE_LABELS[m] for m in connections.modes_for(c["kind"])}
        if not grants:
            ui.label("Ainda não autorizada para nenhum sistema.").classes("text-sm text-gray-500")
        for g in grants:
            with ui.row().classes("w-full items-center gap-2 py-1 no-wrap").props(
                f"data-testid=grant-row:{g['slug']}"
            ):
                with ui.column().classes("gap-1 grow min-w-0"):
                    ui.label(f"{g['system_name']} ({g['slug']})").classes("text-sm font-medium")
                    state = (
                        f"ativa como {g['alias']} · {MODE_LABELS[g['mode']]}" if g["active"] else "não ativada pelo dono"
                    )
                    ui.label(f"{g['owner_email']} · {state}").classes("text-xs text-gray-600")
                    ddl_badge(g["schema_admin_since"])
                ui.select(
                    modes, value=g["max_mode"], label="Teto",
                    on_change=lambda e, c=c, g=g: apply_ceiling(c, g, e.value) if e.value != g["max_mode"] else None,
                ).classes("w-56").props("dense data-testid=grant-ceiling")
                ui.button("Revogar", icon="link_off", on_click=lambda c=c, g=g: ask_revoke(c, g)).props(
                    "dense outline color=warning data-testid=grant-revoke"
                )
        granted = {g["system_id"] for g in grants}
        with ui.row().classes("w-full items-end gap-2 pt-2"):
            options = {k: v for k, v in system_options().items() if k not in granted}
            target = ui.select(options, label="Autorizar para o sistema", with_input=True).classes("grow").props(
                "dense data-testid=grant-system"
            )
            ceiling = ui.select(modes, value="read_write", label="Teto").classes("w-56").props(
                "dense data-testid=grant-ceiling-new"
            )
            ui.button("Autorizar", icon="add_link",
                      on_click=lambda c=c, t=target, m=ceiling: grant(c, t.value, m.value)).props(
                "dense data-testid=grant-submit"
            )

    def refresh() -> None:
        box.clear()
        items = connections.list_catalog()
        with box:
            if not items:
                ui.label("Nenhuma conexão no catálogo. Cadastre a primeira em “Nova conexão”.").classes(
                    "text-gray-500 text-sm"
                ).props("data-testid=catalog-empty")
            for c in items:
                with ui.card().classes("w-full").props(f"data-testid=catalog-conn:{c['name']}"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.label(c["name"]).classes("font-semibold")
                        kind_label(c["kind"])
                        status_badge(c["status"])
                        ui.space()
                        ui.button("Editar", icon="edit", on_click=lambda c=c: form.open_edit(c)).props(
                            "dense flat data-testid=catalog-conn-edit"
                        )
                        ui.button("Excluir", icon="delete", on_click=lambda c=c: ask_delete(c)).props(
                            "dense flat color=negative data-testid=catalog-conn-delete"
                        )
                    if c["description"]:
                        ui.label(c["description"]).classes("text-sm text-gray-600")
                    if c["kind"] == "bigquery":
                        address = f"{c['host']}/{c['database']} · {c['username']}"
                    else:
                        address = f"{c['username']}@{c['host']}:{c['port']}/{c['database']}"
                    ui.label(address).classes("text-xs text-gray-600 font-mono")
                    summary = (
                        f"Autorizada para {c['granted_count']} sistema(s), ativa em {c['active_count']}"
                        if c["granted_count"] else "Sem autorizações"
                    )
                    with ui.expansion(
                        summary, icon="link", value=c["id"] in open_grants,
                        on_value_change=lambda e, cid=c["id"]: track_open(cid, e.value),
                    ).classes("w-full").props(
                        "dense data-testid=catalog-conn-grants"
                    ):
                        render_grants(c)

    refresh()


def _say(label, text: str) -> None:
    """Texto de apoio que só ocupa espaço quando tem conteúdo."""
    label.set_text(text)
    label.set_visibility(bool(text))


class _ConnectionForm:
    """Cadastro e edição de uma conexão do catálogo. O tipo não muda na edição (design D3)."""

    def __init__(self, on_saved) -> None:
        self.on_saved = on_saved
        self.editing: dict | None = None
        with ui.dialog() as self.dialog, ui.card().classes("w-[28rem]"):
            self.title = ui.label("Nova conexão").classes("font-semibold text-lg")
            self.kind = ui.select(KIND_OPTIONS, value="postgres", label="Tipo",
                                  on_change=lambda e: self._on_kind(e.value)).classes("w-full").props(
                "data-testid=conn-kind")
            self.name = ui.input("Nome no catálogo").classes("w-full").props("data-testid=conn-name")
            with ui.column().classes("w-full gap-1") as self.sql_fields:
                self.host = ui.input("Host").classes("w-full").props("data-testid=conn-host")
                self.port = ui.number("Porta", value=5432).classes("w-full").props("data-testid=conn-port")
                self.database = ui.input("Banco").classes("w-full").props("data-testid=conn-database")
                self.username = ui.input("Usuário").classes("w-full").props("data-testid=conn-user")
                self.password = ui.input("Senha", password=True).classes("w-full").props("data-testid=conn-password")
            with ui.column().classes("w-full gap-1") as self.bq_fields:
                self.bq_project = ui.input("Project ID").classes("w-full").props("data-testid=conn-bq-project")
                self.bq_dataset = ui.input("Dataset").classes("w-full").props("data-testid=conn-bq-dataset")
                self.bq_json = ui.textarea("Service Account JSON").classes("w-full").props(
                    "data-testid=conn-bq-sa-json")
                self.bq_email = ui.label("").classes("text-xs text-gray-600")
            self.secret_hint = ui.label("").classes("text-xs text-gray-600")
            self.description = ui.input("Descrição (opcional)").classes("w-full").props(
                "data-testid=conn-description")
            self.affected = ui.label("").classes("text-xs text-gray-600")
            self.feedback = ui.label("").classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancelar", on_click=self.dialog.close).props("flat")
                ui.button("Testar e salvar", icon="check_circle", on_click=self._save).props(
                    "data-testid=save-connection")
        self._reset()
        self._on_kind("postgres")

    def _on_kind(self, kind: str) -> None:
        is_bq = kind == "bigquery"
        self.sql_fields.set_visibility(not is_bq)
        self.bq_fields.set_visibility(is_bq)
        if not is_bq and self.editing is None:
            self.port.set_value(KIND_DEFAULT_PORT.get(kind, 5432))

    def _reset(self) -> None:
        for field in (self.name, self.host, self.database, self.username, self.password, self.bq_project,
                      self.bq_dataset, self.bq_json, self.description):
            field.set_value("")
        _say(self.bq_email, "")
        _say(self.secret_hint, "")
        _say(self.affected, "")
        _say(self.feedback, "")

    def open_new(self) -> None:
        self.editing = None
        self._reset()
        self.title.set_text("Nova conexão")
        self.kind.enable()
        self.kind.set_value("postgres")
        self._on_kind("postgres")
        self.dialog.open()

    def open_edit(self, c: dict) -> None:
        self._reset()
        self.editing = c
        self.title.set_text(f"Editar {c['name']}")
        self.kind.set_value(c["kind"])
        self.kind.disable()
        self._on_kind(c["kind"])
        self.name.set_value(c["name"])
        self.description.set_value(c["description"] or "")
        if c["kind"] == "bigquery":
            self.bq_project.set_value(c["host"])
            self.bq_dataset.set_value(c["database"])
            _say(self.bq_email, f"Service account atual: {c['username']}" if c["username"] else "")
            _say(self.secret_hint, "Deixe o JSON vazio para manter a credencial atual.")
        else:
            self.host.set_value(c["host"])
            self.port.set_value(c["port"])
            self.database.set_value(c["database"])
            self.username.set_value(c["username"])
            _say(self.secret_hint, "Deixe a senha vazia para manter a atual.")
        active = [s for s in connections.connection_systems(c["id"]) if s["active"]]
        if active:
            names = ", ".join(s["slug"] for s in active)
            _say(self.affected, f"Ativa em: {names}. Mudar endereço ou credencial reinicia esses sistemas.")
        self.dialog.open()

    def _values(self) -> tuple:
        kind = self.kind.value or "postgres"
        if kind == "bigquery":
            return kind, self.bq_project.value, 0, self.bq_dataset.value, "", self.bq_json.value
        port = int(self.port.value or KIND_DEFAULT_PORT[kind])
        return kind, self.host.value, port, self.database.value, self.username.value, self.password.value

    def _fail(self, text: str) -> None:
        self.feedback.classes(remove="text-green-600", add="text-red-600")
        _say(self.feedback, text)

    def _save(self) -> None:
        user = get_current_user()
        kind, host, port, database, username, password = self._values()
        try:
            if self.editing is None:
                connections.create_connection(
                    self.name.value, host, port, database, username, password, kind=kind,
                    description=self.description.value or None, actor=user,
                )
            else:
                connections.update_connection(
                    self.editing["id"], self.name.value, host, port, database, username,
                    password=password or None, description=self.description.value or None, actor=user,
                )
        except connections.ConnectionFailed as exc:
            self._fail(f"teste de conexão falhou: {exc}")
            return
        except connections.NameTaken as exc:
            self._fail(str(exc))
            return
        except (ValueError, PermissionError) as exc:
            self._fail(str(exc))
            return
        self.dialog.close()
        notify("Conexão salva.", "positive")
        self.on_saved()


def _degraded_panel() -> None:
    """Conexões do catálogo com falha de conectividade (design D11)."""
    ui.label("Conexões de banco com falha de conectividade detectada pelo reconciliador.").classes(
        "text-sm text-gray-600 mb-3"
    )
    box = ui.column().classes("w-full max-w-4xl gap-2").props("data-testid=degraded-connections-box")

    def refresh() -> None:
        box.clear()
        items = connections.list_degraded_connections()
        with box:
            if not items:
                ui.label("Nenhuma conexão degradada no momento.").classes("text-gray-500 text-sm").props(
                    "data-testid=no-degraded-connections"
                )
                return
            for item in items:
                with ui.card().classes("w-full").props(f"data-testid=degraded-conn:{item['name']}"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning").classes("text-red-600")
                        ui.label(item["name"]).classes("font-semibold")
                        ui.label(f"{KIND_OPTIONS.get(item['kind'], item['kind'])} · {item['host']}").classes(
                            "text-sm text-gray-600"
                        )
                    used = ", ".join(f"{s['name']} ({s['slug']})" for s in item["systems"]) or "nenhum sistema"
                    ui.label(f"Autorizada para: {used}").classes("text-sm text-gray-600")

    refresh()
    ui.timer(30.0, refresh)
