"""Páginas de login (specs portal-identity, oidc-authentication).

- `/login`: modo local -> formulário e-mail/senha; modo oidc -> entrada pelo IdP
  (redireciona sozinho quando chega com `next`, para o link de uma app voltar a ela).
- `/login/local`: formulário e-mail/senha nos dois modos — no oidc, só o admin
  break-glass entra por aqui (não há link para ela nas páginas).

O formulário envia as credenciais para `POST /auth/local`, que grava o cookie de
sessão HttpOnly na resposta; mensagem de falha é sempre genérica.
"""

import json
from urllib.parse import quote

from fastapi import Request
from nicegui import ui

from ..auth_mode import is_oidc
from ..auth_routes import safe_next
from . import theme
from .common import render_theme_css

_ERRORS = {
    "acesso_negado": "Acesso não concedido: sua conta não tem um papel válido no portal. "
                     "Solicite acesso pelo processo da sua organização.",
    "falha": "Não foi possível concluir o login. Tente novamente.",
}

_LOGIN_JS = """
const r = await fetch('/auth/local', {{
  method: 'POST', credentials: 'same-origin',
  headers: {{'Content-Type': 'application/json'}},
  body: JSON.stringify({payload}),
}});
let j = {{ok: false, error: 'falha'}};
try {{ j = await r.json(); }} catch (e) {{}}
if (j.ok) {{ window.location = j.next; }}
return j.ok ? 'ok' : (j.error || 'falha');
"""


def _render_local_form(next_path: str, subtitle: str) -> None:
    with ui.card().classes("w-96 mx-auto mt-24"):
        ui.label("AIDB").classes("text-2xl font-bold")
        ui.label(subtitle).classes("text-sm text-gray-500")
        email = ui.input("E-mail").classes("w-full").props("data-testid=login-email")
        password = ui.input("Senha", password=True, password_toggle_button=True).classes("w-full").props("data-testid=login-password")
        error = ui.label("").classes("text-red-600 text-sm").props("data-testid=login-error")

        async def try_login() -> None:
            payload = json.dumps({"email": email.value or "", "password": password.value or "", "next": next_path})
            result = await ui.run_javascript(_LOGIN_JS.format(payload=payload), timeout=15)
            if result == "ok":
                return
            if result == "bloqueado":
                error.set_text("Muitas tentativas. Aguarde alguns minutos e tente de novo.")
            else:
                error.set_text("E-mail ou senha inválidos.")

        password.on("keydown.enter", try_login)
        ui.button("Entrar", on_click=try_login).classes("w-full mt-2").props("data-testid=login-submit")


def register() -> None:
    @ui.page("/login")
    def login_page(request: Request) -> None:
        render_theme_css(theme.DEFAULT_THEME)
        next_path = safe_next(request.query_params.get("next"))
        if not is_oidc():
            _render_local_form(next_path, "Entre para acessar o portal")
            return

        error_key = request.query_params.get("erro")
        sso_url = "/auth/login" + ("" if next_path == "/" else f"?next={quote(next_path, safe='')}")
        if request.query_params.get("next") and not error_key:
            # veio de um link protegido (página ou app): segue direto para o IdP
            ui.navigate.to(sso_url)
        with ui.card().classes("w-96 mx-auto mt-24"):
            ui.label("AIDB").classes("text-2xl font-bold")
            ui.label("Entre com a conta da sua organização").classes("text-sm text-gray-500")
            if error_key:
                ui.label(_ERRORS.get(error_key, _ERRORS["falha"])).classes(
                    "text-red-600 text-sm"
                ).props("data-testid=login-error")
            ui.button("Entrar com SSO", on_click=lambda: ui.navigate.to(sso_url)).classes(
                "w-full mt-2"
            ).props("data-testid=login-sso")

    @ui.page("/login/local")
    def login_local_page(request: Request) -> None:
        render_theme_css(theme.DEFAULT_THEME)
        next_path = safe_next(request.query_params.get("next"))
        subtitle = "Acesso de emergência" if is_oidc() else "Entre para acessar o portal"
        _render_local_form(next_path, subtitle)
