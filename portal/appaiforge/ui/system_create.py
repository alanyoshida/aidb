"""Criação de sistema (somente editor/admin; spec system-management)."""

from nicegui import ui

from ..services import catalog
from ..services.systems import (
    KIND_AGENT, KIND_DEPLOY_ONLY, AgentNotAllowedHere, InvalidSlug, NotPermitted, SlugTaken, create_system,
    is_production,
)
from .common import get_current_user, redirect_to_login, notify, render_header


def register() -> None:
    @ui.page("/systems/new")
    def new_system_page() -> None:
        user = get_current_user()
        if user is None:
            redirect_to_login()
            return
        render_header(user)
        if not user.is_editor and not user.is_admin:
            ui.label("Somente editores podem criar sistemas.").classes("text-red-600 m-8")
            return

        ui.label("Novo sistema").classes("text-2xl font-bold m-4")
        with ui.card().classes("w-96"):
            name = ui.input("Nome").classes("w-full").props("data-testid=system-name")
            slug = ui.input("Slug (kebab-case)").classes("w-full").props("data-testid=system-slug")
            production = is_production()
            # Tipo do sistema (change add-deploy-only-system): num portal de produção só existe
            # "só implantação", sem escolha e sem provedor de LLM.
            if production:
                kind = None
                ui.label("Sistema só implantação: implanta versões aprovadas de um repositório GitLab.").classes(
                    "text-sm text-gray-500").props("data-testid=system-kind-fixed")
            else:
                kind = ui.radio({KIND_AGENT: "Com agente (chat e geração)", KIND_DEPLOY_ONLY: "Só implantação"},
                                value=KIND_AGENT).props("data-testid=system-kind")
            provider_ids = [p["id"] for p in catalog.list_providers()] or ["glm"]
            provider = ui.select(provider_ids, value="glm", label="Provedor de LLM").classes("w-full").props("data-testid=system-provider")
            if production:
                provider.set_visibility(False)
            else:
                provider.bind_visibility_from(kind, "value", backward=lambda v: v == KIND_AGENT)
            feedback = ui.label("").classes("text-sm")

            def create() -> None:
                try:
                    chosen = KIND_DEPLOY_ONLY if production else kind.value
                    system = create_system(user, name.value, slug.value,
                                           provider.value if chosen == KIND_AGENT else None, kind=chosen)
                except SlugTaken:
                    feedback.classes("text-red-600 text-sm").set_text(f"slug '{slug.value}' já existe")
                    return
                except (InvalidSlug, NotPermitted, AgentNotAllowedHere) as exc:
                    feedback.classes("text-red-600 text-sm").set_text(str(exc))
                    return
                from ..provisioning import start_provisioning_thread

                start_provisioning_thread(system.id)
                notify("Sistema criado; provisionando container...", "info")
                ui.navigate.to(f"/systems/{system.id}")

            # alinhado à direita, como todo diálogo de confirmação do
            # portal (justify-end) — era o único botão de "enviar formulário"
            # que ficava à esquerda, sem seguir o padrão (achado do critique)
            with ui.row().classes("w-full justify-end"):
                ui.button("Criar sistema", icon="add", on_click=create).props("data-testid=create-system")
