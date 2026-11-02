"""Helpers compartilhados das páginas (usuário corrente, cookie de sessão, header)."""

from nicegui import ui

from .. import auth
from ..models import User

SET_COOKIE_JS = "document.cookie = 'appaiforge_session={token}; path=/; max-age={max_age}; SameSite=Lax'"
CLEAR_COOKIE_JS = "document.cookie = 'appaiforge_session=; path=/; max-age=0; SameSite=Lax'"


def get_current_user() -> User | None:
    """Usuário da sessão corrente (cookie), ou None."""
    token = ui.context.client.request.cookies.get(auth.COOKIE_NAME)
    return auth.resolve_user(token)


def current_token() -> str | None:
    return ui.context.client.request.cookies.get(auth.COOKIE_NAME)


def require_user() -> User:
    user = get_current_user()
    if user is None:
        ui.navigate.to("/login")
        raise RuntimeError("redirect para /login")
    return user


def render_header(user: User) -> None:
    """Header comum a todas as páginas autenticadas (navegação + logout)."""
    with ui.header().classes("items-center justify-between bg-dark"):
        ui.label("AppAIForge").classes("text-xl font-bold cursor-pointer").on("click", lambda: ui.navigate.to("/"))
        with ui.row().classes("items-center"):
            if user.is_admin:
                ui.button("Administração", on_click=lambda: ui.navigate.to("/admin")).props("flat dense")
                ui.button("Guidelines", on_click=lambda: ui.navigate.to("/admin/guidelines")).props("flat dense")
            ui.label(user.email).classes("text-sm")
            ui.label(f"({user.type.value})").classes("text-xs text-gray-400")

            def do_logout() -> None:
                auth.logout(current_token())
                ui.run_javascript(CLEAR_COOKIE_JS + "; window.location = '/login'")

            ui.button("Sair", on_click=do_logout).props("flat dense")
