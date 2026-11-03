"""Editor de guidelines de geração (somente admin; spec agent-harness)."""

from nicegui import ui

from .. import guidelines
from .common import get_current_user, render_header


def register() -> None:
    @ui.page("/admin/guidelines")
    def guidelines_page() -> None:
        user = get_current_user()
        if user is None:
            ui.navigate.to("/login")
            return
        render_header(user)
        if not user.is_admin:
            ui.label("Permissão insuficiente.").classes("text-red-600 m-8")
            return

        ui.label("Guidelines de geração").classes("text-2xl font-bold m-4")
        ui.label("Aplicadas a todos os agentes a partir das próximas execuções.").classes("text-sm text-gray-500 m-4")
        editor = ui.textarea(value=guidelines.current_content()).classes("w-full max-w-4xl mx-4").props("rows=20 data-testid=guidelines-editor")
        feedback = ui.label("").classes("mx-4 text-sm")

        def save() -> None:
            version = guidelines.update_content(editor.value, user.id, user.email)
            feedback.classes("text-green-600 text-sm").set_text(f"guidelines v{version} salvas")

        ui.button("Salvar", icon="save", on_click=save).props("data-testid=save-guidelines mx-4")
