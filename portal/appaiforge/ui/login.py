"""Login local e-mail/senha (spec portal-identity: mensagem genérica em falha)."""

from nicegui import app, ui

from .. import auth
from ..config import get_settings
from .common import SET_COOKIE_JS


def register() -> None:
    @ui.page("/login")
    def login_page() -> None:
        with ui.card().classes("w-96 mx-auto mt-24"):
            ui.label("AIDB").classes("text-2xl font-bold")
            ui.label("Entre para acessar o portal").classes("text-sm text-gray-500")
            email = ui.input("E-mail").classes("w-full").props("data-testid=login-email")
            password = ui.input("Senha", password=True, password_toggle_button=True).classes("w-full").props("data-testid=login-password")
            error = ui.label("").classes("text-red-600 text-sm")

            def try_login() -> None:
                try:
                    token = auth.authenticate(email.value, password.value)
                except auth.LoginRejected:
                    error.set_text("E-mail ou senha inválidos.")
                    return
                # atômico no browser: grava o cookie e só então navega (sem corrida)
                ui.run_javascript(
                    SET_COOKIE_JS.format(token=token, max_age=get_settings().session_ttl_days * 86400)
                    + "; window.location = '/'"
                )

            password.on("keydown.enter", try_login)
            ui.button("Entrar", on_click=try_login).classes("w-full mt-2")
