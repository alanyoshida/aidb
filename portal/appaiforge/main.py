"""Aplicação FastAPI + NiceGUI do portal."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from nicegui import ui

from . import __version__, auth, security
from .db import get_engine
from .edge import write_portal_router
from .models import Base, User, UserType
from .ui import register_pages


def _seed_demo_admin() -> None:
    """Bootstrap de desenvolvimento: cria admin padrão se APPAIFORGE_SEED_DEMO_ADMIN=1
    e não há nenhum usuário. Em produção, use `appaiforge create-admin`."""
    if os.environ.get("APPAIFORGE_SEED_DEMO_ADMIN") != "1":
        return
    from sqlalchemy import func, select

    from . import auth
    from .db import session_scope

    with session_scope() as s:
        if s.execute(select(func.count(User.id))).scalar_one() == 0:
            s.add(User(email="admin@appaiforge.local", password_hash=security.hash_password("admin123"), type=UserType.admin))


def create_app() -> FastAPI:
    application = FastAPI(title="AppAIForge", version=__version__)
    get_engine()
    Base.metadata.create_all(get_engine())  # Alembic é o caminho normal; create_all garante dev/boot
    _seed_demo_admin()

    from .agent_queue import reconcile_orphaned_runs

    reconcile_orphaned_runs()

    @application.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @application.get("/entry/{slug}")
    def app_entry(slug: str, request: Request) -> "RedirectResponse":
        """Porta de entrada da app (fora do prefixo /apps, que é roteado
        direto ao container pelo Traefik): valida acesso e assina o token."""
        from fastapi.responses import RedirectResponse

        from .config import get_settings
        from .models import SystemStatus
        from .rbac import can_access_system
        from .services.systems import get_system_by_slug
        from .ui.common import get_current_user

        auth_cookie = request.cookies.get(auth.COOKIE_NAME)
        user = auth.resolve_user(auth_cookie)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        system = get_system_by_slug(slug)
        if system is None or system.status != SystemStatus.active or not can_access_system(user, system.id):
            return RedirectResponse("/", status_code=302)
        token = security.sign_identity_token(
            system.identity_secret,
            {"user_id": user.id, "user_type": user.type.value, "email": user.email},
            ttl_seconds=get_settings().identity_token_ttl_seconds,
        )
        return RedirectResponse(f"/apps/{slug}/?t={token}", status_code=302)

    register_pages()
    write_portal_router()
    from .health_monitor import start_monitor

    start_monitor()
    ui.run_with(application, title="AppAIForge")
    return application


app = create_app()
