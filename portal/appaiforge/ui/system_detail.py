"""Detalhe do sistema: estado, provedor e conexões de banco (specs system-management, db-connections)."""

from nicegui import ui

from ..models import System
from ..rbac import can_access_system, can_manage_system
from ..services import connections
from ..services.systems import get_system
from .common import get_current_user, render_header

_STATUS_LABEL = {"provisioning": "provisionando", "active": "ativo", "error": "erro", "archived": "arquivado"}
_STATUS_COLOR = {"active": "positive", "provisioning": "warning", "error": "negative"}


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
            ui.label(system.name).classes("text-gray-300")
        ui.label(system.name).classes("text-2xl font-bold mx-4 mt-1")
        with ui.row().classes("mx-4 items-center"):
            ui.label(f"/{system.slug}").classes("text-gray-500")
            status_badge = ui.badge(_STATUS_LABEL.get(system.status.value, system.status.value))
            if can_manage_system(user, system):
                ui.label(f"provedor: {system.provider} / modelo: {system.model}").classes("text-sm text-gray-600")

        open_btn = ui.button("Abrir app", icon="open_in_new", on_click=lambda: ui.navigate.to(f"/entry/{system.slug}", new_tab=True)).props("data-testid=open-app")
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

        # ciclo de vida: arquivar (dono) e excluir definitivamente (admin, arquivado)
        with ui.row().classes("mx-4 mt-2"):

            def archive() -> None:
                from ..provisioning import archive_system

                archive_system(system)
                ui.navigate.to("/")

            ui.button("Arquivar sistema", icon="archive", on_click=archive).props("color=warning outline data-testid=archive-system")

            if user.is_admin and system.status.value == "archived":

                def delete() -> None:
                    from ..provisioning import delete_system

                    delete_system(system)
                    ui.navigate.to("/")

                ui.button("Excluir definitivamente", icon="delete_forever", on_click=delete).props("color=negative data-testid=delete-system")

        with ui.tabs().classes("mx-4 w-full") as tabs:
            chat_tab = ui.tab("chat", label="Chat", icon="chat")
            conn_tab = ui.tab("conn", label="Conexões", icon="storage")
            ckpt_tab = ui.tab("ckpt", label="Checkpoints", icon="history")
            audit_tab = ui.tab("audit", label="Auditoria", icon="shield")

        with ui.tab_panels(tabs, value=chat_tab).classes("mx-4 w-full"):
            with ui.tab_panel(chat_tab):
                from .chat import render_chat

                render_chat(system, user)
            with ui.tab_panel(conn_tab):
                _render_connections(system)
            with ui.tab_panel(ckpt_tab):
                _render_checkpoints(system)
            with ui.tab_panel(audit_tab):
                _render_gate_history(system)
                _render_usage(system)


def _render_connections(system) -> None:
    """Conexões de banco: lista + formulário de nova conexão (spec db-connections)."""
    ui.label("Bancos de dados que o agente e a app podem acessar").classes("text-sm text-gray-500 mb-2")

    with ui.dialog() as conn_dialog, ui.card().classes("w-96"):
        ui.label("Nova conexão PostgreSQL").classes("font-semibold text-lg")
        cname = ui.input("Nome").classes("w-full").props("data-testid=conn-name")
        chost = ui.input("Host").classes("w-full").props("data-testid=conn-host")
        cport = ui.number("Porta", value=5432).classes("w-full").props("data-testid=conn-port")
        cdb = ui.input("Banco").classes("w-full").props("data-testid=conn-database")
        cuser = ui.input("Usuário").classes("w-full").props("data-testid=conn-user")
        cpass = ui.input("Senha", password=True).classes("w-full").props("data-testid=conn-password")
        feedback = ui.label("").classes("text-sm")

        def add_conn() -> None:
            try:
                connections.register_connection(
                    system, cname.value, chost.value, int(cport.value or 5432), cdb.value, cuser.value, cpass.value,
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
        for field in (cname, chost, cdb, cuser, cpass):
            field.set_value("")
        cport.set_value(5432)
        feedback.set_text("")
        conn_dialog.open()

    ui.button("Nova conexão", icon="add", on_click=open_conn_dialog).classes("mb-3")

    conns_box = ui.column().classes("w-full max-w-3xl")

    def refresh_conns() -> None:
        conns_box.clear()
        conns = connections.list_connections(system.id)
        with conns_box:
            if not conns:
                ui.label("Nenhuma conexão cadastrada ainda.").classes("text-gray-500 text-sm")
            for c in conns:
                with ui.card().classes("w-full"):
                    ui.label(f"{c['name']}").classes("font-semibold")
                    ui.label(f"{c['kind']} · {c['username']}@{c['host']}:{c['port']}/{c['database']}").classes("text-sm text-gray-600")

    refresh_conns()


def _render_checkpoints(system) -> None:
    from .. import checkpoints as cp_service

    ui.label("Pontos salvos do código da app — restaure a qualquer um deles").classes("text-sm text-gray-500 mb-2")
    ui.button("Criar checkpoint agora", icon="add", on_click=lambda: (cp_service.record_checkpoint(system, None, "checkpoint manual"), refresh_cps())).props("outline dense")
    timeline_container = ui.column().classes("w-full max-w-3xl mt-2")

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
                        ui.notify(f"workspace restaurado para {sha[:8]}", type="positive")

                    with ui.timeline_entry(title=cp["git_sha"][:8], icon="commit"):
                        ui.label(cp["message"][:140]).classes("text-sm")
                        ui.button("Restaurar", icon="restore", on_click=do_rollback).props("dense outline")

    refresh_cps()
    ui.timer(2.0, refresh_cps)


def _render_usage(system) -> None:
    from sqlalchemy import select

    from ..db import session_scope
    from ..models import AgentRun, TokenUsage, User

    ui.label("Uso de tokens").classes("text-lg font-semibold mt-6")
    ui.label("Consumo de LLM agrupado por execução, para acompanhar custo").classes("text-sm text-gray-500 mb-2")
    total_label = ui.label("").classes("text-sm font-semibold")
    detail_box = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh_usage() -> None:
        with session_scope() as s:
            rows = s.execute(
                select(TokenUsage, User.email, AgentRun.prompt)
                .outerjoin(User, User.id == TokenUsage.user_id)
                .outerjoin(AgentRun, AgentRun.id == TokenUsage.run_id)
                .where(TokenUsage.system_id == system.id)
                .order_by(TokenUsage.created_at.desc())
            ).all()
        total_in = sum(usage.input_tokens for usage, _, _ in rows)
        total_out = sum(usage.output_tokens for usage, _, _ in rows)
        total_label.set_text(f"total: {total_in:,} entrada / {total_out:,} saída")

        execs: dict[str, dict] = {}
        for usage, email, prompt in rows:
            group = execs.setdefault(
                usage.run_id,
                {"provider": usage.provider, "model": usage.model, "email": email, "prompt": prompt, "tin": 0, "tout": 0},
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
                    ui.label(f"({d['origin']} · autor: {autor})").classes("text-xs text-gray-500")

    refresh_gate()
    ui.timer(2.0, refresh_gate)
