"""Criação de sistema (somente editor/admin; spec system-management)."""

from nicegui import ui

from ..services import catalog
from ..services.systems import InvalidSlug, NotPermitted, SlugTaken, create_system
from .common import get_current_user, notify, render_header


def register() -> None:
    @ui.page("/systems/new")
    def new_system_page() -> None:
        user = get_current_user()
        if user is None:
            ui.navigate.to("/login")
            return
        render_header(user)
        if not user.is_editor and not user.is_admin:
            ui.label("Somente editores podem criar sistemas.").classes("text-red-600 m-8")
            return

        ui.label("Novo sistema").classes("text-2xl font-bold m-4")
        with ui.card().classes("w-96"):
            name = ui.input("Nome").classes("w-full").props("data-testid=system-name")
            slug = ui.input("Slug (kebab-case)").classes("w-full").props("data-testid=system-slug")
            provider_ids = [p["id"] for p in catalog.list_providers()] or ["glm"]
            provider = ui.select(provider_ids, value="glm", label="Provedor de LLM").classes("w-full").props("data-testid=system-provider")
            feedback = ui.label("").classes("text-sm")

            def create() -> None:
                try:
                    system = create_system(user, name.value, slug.value, provider.value)
                except SlugTaken:
                    feedback.classes("text-red-600 text-sm").set_text(f"slug '{slug.value}' já existe")
                    return
                except (InvalidSlug, NotPermitted) as exc:
                    feedback.classes("text-red-600 text-sm").set_text(str(exc))
                    return
                from ..provisioning import start_provisioning_thread

                start_provisioning_thread(system.id)
                notify("Sistema criado; provisionando container...", "info")
                ui.navigate.to(f"/systems/{system.id}")

            ui.button("Criar sistema", icon="add", on_click=create).props("data-testid=create-system")
