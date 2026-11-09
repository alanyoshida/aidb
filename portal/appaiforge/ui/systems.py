"""Área de sistemas do portal: listagem com visibilidade por permissão.

A criação/gestão completa entra com o serviço de sistemas (task 3.1/3.4);
a listagem já honra a visibilidade da spec system-management.
"""

from nicegui import ui
from sqlalchemy import select

from ..db import session_scope
from ..models import System, User
from ..rbac import can_create_systems, visible_system_ids

_STATUS_LABEL = {
    "provisioning": "provisionando",
    "active": "ativo",
    "error": "erro",
    "archived": "arquivado",
}


def render_systems_area(user: User) -> None:
    with session_scope() as s:
        ids = visible_system_ids(user)
        systems = s.execute(select(System).where(System.id.in_(ids)).order_by(System.created_at)).scalars().all() if ids else []
        rows = [(sys.id, sys.slug, sys.name, sys.status.value, sys.status_message) for sys in systems]

    ui.label("Sistemas").classes("text-lg font-semibold mt-4")
    if can_create_systems(user):
        with ui.row():
            ui.button("Novo sistema", icon="add", on_click=lambda: ui.navigate.to("/systems/new"))

    if not rows:
        ui.label("Nenhum sistema acessível.").classes("text-gray-500")
        return

    # sem columns=3 (vira style inline de alta especificidade, que a media
    # query do tema não conseguiria vencer sem !important) — a largura das
    # colunas mora em CSS (theme.py), que já reduz pra 1-2 colunas em telas
    # estreitas. 3 colunas fixas espremiam cada card/link de navegação a
    # ~115px no mobile, forçando o nome a quebrar em 2-3 linhas (achado do
    # critique).
    with ui.grid().classes("w-full gap-4 af-systems-grid"):
        for system_id, slug, name, status, status_message in rows:
            with ui.card().on("click", lambda sid=system_id: ui.navigate.to(f"/systems/{sid}")):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("dns").classes("text-gray-500")
                    ui.label(name).classes("font-semibold")
                ui.label(f"/{slug}").classes("text-xs text-gray-500")
                with ui.row().classes("items-center"):
                    badge = ui.badge(_STATUS_LABEL.get(status, status))
                    if status == "active":
                        badge.props("color=positive")
                    elif status == "error":
                        badge.props("color=negative")
                    elif status == "provisioning":
                        badge.props("color=warning")
                    else:
                        badge.props("color=neutral text-color=neutraltext")
                if status == "error" and status_message:
                    ui.label(status_message).classes("text-xs text-red-600")
