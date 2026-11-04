"""Helpers compartilhados das páginas (usuário corrente, cookie de sessão, header)."""

from nicegui import ui

from .. import auth
from ..models import User
from . import theme

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


_NOTIFY_ICON = {
    "info": "info",
    "positive": "check_circle",
    "negative": "error",
    "warning": "warning",
}


def notify(message: str, kind: str = "info") -> None:
    """Notificação nas cores do tema.

    Evita o `type` do Quasar de propósito: ele aplica uma classe `bg-*` cujo
    fundo vence o nosso CSS, deixando texto claro sobre ciano (1.6:1) ou verde
    (2.1:1). Sem essa classe, a folha do portal pinta a superfície normalmente.
    """
    ui.notify(
        message,
        icon=_NOTIFY_ICON.get(kind, "info"),
        classes=f"ap-notify ap-notify--{kind}",
    )


def render_theme_menu(user: User) -> None:
    """Seletor de tema (modo + cor) da topbar; grava a escolha em User.theme."""
    from ..db import session_scope

    state = dict(zip(("mode", "accent"), theme.parse_key(user.theme)))

    def persist_and_apply() -> None:
        key = f"{state['mode']}-{state['accent']}"
        with session_scope() as s:
            row = s.get(User, user.id)
            if row is not None:
                row.theme = key
        # Recarrega: o head já sai com os tokens do usuário, então tudo (inclusive
        # os avatares SVG do chat) fica consistente sem flash.
        ui.navigate.reload()

    def pick_mode(mode: str) -> None:
        state["mode"] = mode
        persist_and_apply()

    def pick_accent(accent: str) -> None:
        state["accent"] = accent
        persist_and_apply()

    @ui.refreshable
    def panel() -> None:
        with ui.column().classes("p-3 gap-2 min-w-56"):
            ui.label("Modo").classes("text-xs font-semibold")
            with ui.row().classes("gap-1"):
                for mode in theme.MODES:
                    on = state["mode"] == mode
                    (ui.button(theme.MODE_LABELS[mode], icon=theme.MODE_ICONS[mode],
                               on_click=lambda m=mode: pick_mode(m))
                     .props(f"dense no-caps {'unelevated color=primary' if on else 'flat'}")
                     .classes("text-xs"))
            ui.separator()
            ui.label("Cor de destaque").classes("text-xs font-semibold")
            with ui.row().classes("gap-2 items-center"):
                for accent_id, accent in theme.ACCENTS.items():
                    on = state["accent"] == accent_id
                    (ui.button(on_click=lambda a=accent_id: pick_accent(a))
                     .props("flat dense round")
                     .classes("ap-swatch" + (" ap-swatch--on" if on else ""))
                     .style(f"background:{accent['base']}")
                     .tooltip(accent["name"]))

    with ui.dropdown_button(icon="palette").props(
        "flat dense round data-testid=theme-menu"
    ):
        panel()


def render_header(user: User) -> None:
    """Header comum a todas as páginas autenticadas (navegação + menu do usuário)."""
    def do_logout() -> None:
        auth.logout(current_token())
        ui.run_javascript(CLEAR_COOKIE_JS + "; window.location = '/login'")

    tokens = theme.tokens(*theme.parse_key(user.theme))
    # O NiceGUI injeta a paleta do Quasar depois do nosso head, e preenche com os
    # defaults dele toda cor que não for passada — por isso todas vão aqui, senão
    # positive/negative/warning voltam ao padrão e ignoram o tema.
    # `neutral`/`neutraltext` são cores próprias, usadas nos badges de estado ausente.
    ui.colors(
        primary=tokens["--ap-accent"],
        dark=tokens["--ap-bg"],
        positive=tokens["--ap-success"],
        negative=tokens["--ap-danger"],
        warning=tokens["--ap-warning"],
        info=tokens["--ap-accent"],
        neutral=tokens["--ap-surface-2"],
        neutraltext=tokens["--ap-muted"],
    )
    ui.add_head_html(theme.head_html(user.theme))

    with ui.header().classes("items-center justify-between"):
        ui.label("AIDB").classes("text-xl font-bold cursor-pointer ap-brand").on("click", lambda: ui.navigate.to("/"))
        with ui.row().classes("items-center gap-2"):
            if user.is_admin:
                ui.button("Administração", on_click=lambda: ui.navigate.to("/admin")).props("flat dense")
            render_theme_menu(user)
            with ui.dropdown_button(icon="account_circle").props(
                "flat dense round data-testid=user-menu"
            ):
                with ui.column().classes("p-3 gap-1 min-w-48"):
                    ui.label(user.email).classes("text-sm font-semibold")
                    ui.label(f"({user.type.value})").classes("text-xs text-gray-500")
                    ui.separator()
                    ui.menu_item("Sair", on_click=do_logout).props("data-testid=logout")
