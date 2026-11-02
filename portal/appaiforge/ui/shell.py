"""Shell autenticado do portal: raiz com lista de sistemas e navegação.

O conteúdo por papel (sistemas, admin) é preenchido pelos módulos de cada
capability; aqui fica a moldura comum com logout.
"""

from nicegui import ui

from .common import get_current_user, render_header


def register() -> None:
    @ui.page("/")
    def index_page() -> None:
        user = get_current_user()
        if user is None:
            ui.navigate.to("/login")
            return

        render_header(user)

        from .systems import render_systems_area

        with ui.column().classes("w-full max-w-5xl mx-auto p-4"):
            render_systems_area(user)
