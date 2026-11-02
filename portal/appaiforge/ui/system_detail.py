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
        ui.label(system.name).classes("text-2xl font-bold m-4")
        with ui.row().classes("mx-4 items-center"):
            ui.label(f"/{system.slug}").classes("text-gray-500")
            status_badge = ui.badge(_STATUS_LABEL.get(system.status.value, system.status.value))
            if can_manage_system(user, system):
                ui.label(f"provedor: {system.provider} / modelo: {system.model}").classes("text-sm text-gray-600")

        open_btn = ui.button("Abrir app", on_click=lambda: ui.navigate.to(f"/entry/{system.slug}", new_tab=True)).props("data-testid=open-app")
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

            ui.button("Arquivar sistema", on_click=archive).props("color=warning outline data-testid=archive-system")

            if user.is_admin and system.status.value == "archived":

                def delete() -> None:
                    from ..provisioning import delete_system

                    delete_system(system)
                    ui.navigate.to("/")

                ui.button("Excluir definitivamente", on_click=delete).props("color=negative data-testid=delete-system")

        ui.label("Conexões de banco").classes("text-lg font-semibold mx-4 mt-4")
        conns_box = ui.column().classes("mx-4 w-full max-w-3xl")

        def refresh_conns() -> None:
            conns_box.clear()
            for c in connections.list_connections(system.id):
                with conns_box:
                    with ui.card().classes("w-full"):
                        ui.label(f"{c['name']}").classes("font-semibold")
                        ui.label(f"{c['kind']} · {c['username']}@{c['host']}:{c['port']}/{c['database']}").classes("text-sm text-gray-600")

        with ui.card().classes("mx-4 w-full max-w-3xl"):
            ui.label("Nova conexão PostgreSQL").classes("font-semibold")
            cname = ui.input("Nome").props("data-testid=conn-name")
            chost = ui.input("Host").props("data-testid=conn-host")
            cport = ui.number("Porta", value=5432).props("data-testid=conn-port")
            cdb = ui.input("Banco").props("data-testid=conn-database")
            cuser = ui.input("Usuário").props("data-testid=conn-user")
            cpass = ui.input("Senha", password=True).props("data-testid=conn-password")
            feedback = ui.label("").classes("text-sm")

            def add_conn() -> None:
                try:
                    connections.register_connection(
                        system, cname.value, chost.value, int(cport.value or 5432), cdb.value, cuser.value, cpass.value,
                    )
                except connections.ConnectionFailed as exc:
                    feedback.classes("text-red-600 text-sm").set_text(f"teste de conexão falhou: {exc}")
                    return
                except connections.NameTaken:
                    feedback.classes("text-red-600 text-sm").set_text(f"conexão '{cname.value}' já existe")
                    return
                feedback.classes("text-green-600 text-sm").set_text("conexão cadastrada")
                for field in (cname, chost, cdb, cuser, cpass):
                    field.set_value("")
                refresh_conns()

            ui.button("Testar e salvar", on_click=add_conn).props("data-testid=save-connection")
        refresh_conns()

        ui.label("Chat de geração").classes("text-lg font-semibold mx-4 mt-6")
        from .chat import render_chat

        with ui.card().classes("mx-4 w-full max-w-3xl"):
            render_chat(system, user)

        if can_manage_system(user, system):
            _render_checkpoints(system)
            _render_gate_history(system)
            _render_usage(system)


def _render_checkpoints(system) -> None:
    from .. import checkpoints as cp_service

    listing = ui.column().classes("mx-4 w-full max-w-3xl")

    def refresh_cps() -> None:
        listing.clear()
        try:
            cps = cp_service.list_checkpoints(system)
        except Exception:
            cps = []
        with listing:
            if not cps:
                ui.label("Nenhum checkpoint ainda.").classes("text-gray-500 text-sm")
            for cp in cps:
                with ui.row().classes("w-full items-center"):
                    ui.label(f"{cp['git_sha'][:8]} — {cp['message'][:70]}").classes("text-sm")
                    ui.space()

                    def do_rollback(sha=cp["git_sha"]) -> None:
                        cp_service.rollback(system, sha)
                        ui.notify(f"workspace restaurado para {sha[:8]}", type="positive")

                    ui.button("Restaurar", on_click=do_rollback).props("dense outline")

    ui.label("Checkpoints").classes("text-lg font-semibold mx-4 mt-6")
    ui.button("Criar checkpoint agora", on_click=lambda: (cp_service.record_checkpoint(system, None, "checkpoint manual"), refresh_cps())).props("outline dense mx-4")
    refresh_cps()
    ui.timer(2.0, refresh_cps)


def _render_usage(system) -> None:
    from sqlalchemy import select

    from ..db import session_scope
    from ..models import TokenUsage

    ui.label("Uso de tokens").classes("text-lg font-semibold mx-4 mt-6")
    total_label = ui.label("").classes("mx-4 text-sm")
    detail_box = ui.column().classes("mx-4")

    def refresh_usage() -> None:
        with session_scope() as s:
            rows = s.execute(
                select(TokenUsage.provider, TokenUsage.model, TokenUsage.user_id, TokenUsage.input_tokens, TokenUsage.output_tokens)
                .where(TokenUsage.system_id == system.id)
            ).all()
        total_in = sum(r[3] for r in rows)
        total_out = sum(r[4] for r in rows)
        total_label.set_text(f"total: {total_in:,} entrada / {total_out:,} saída")
        detail_box.clear()
        with detail_box:
            for provider, model, user_id, tin, tout in rows:
                ui.label(f"{provider}/{model} · {user_id[:8]}… · {tin:,}/{tout:,}").classes("text-xs text-gray-500")

    refresh_usage()
    ui.timer(2.0, refresh_usage)


def _render_gate_history(system) -> None:
    """Histórico de decisões do gate (spec destructive-gate: auditoria)."""
    from .. import gate as gate_service

    ui.label("Gate de destrutivas").classes("text-lg font-semibold mx-4 mt-6")
    rows_box = ui.column().classes("mx-4 w-full max-w-3xl")

    def refresh_gate() -> None:
        decisions = gate_service.list_decisions(system.id, limit=20)
        rows_box.clear()
        with rows_box:
            if not decisions:
                ui.label("Nenhuma decisão do gate ainda.").classes("text-gray-500 text-sm")
            for d in decisions:
                color = {"bloqueada": "text-red-600", "recusada": "text-orange-600", "aprovada": "text-green-700"}.get(d["decision"], "")
                autor = d["author_id"][:8] + "…" if d["author_id"] else "—"
                with ui.row().classes("w-full items-center"):
                    ui.label(f"[{d['decision']}] {d['sql'][:70]}").classes(f"text-sm {color}")
                    ui.label(f"({d['origin']} · autor: {autor})").classes("text-xs text-gray-500")

    refresh_gate()
    ui.timer(2.0, refresh_gate)
