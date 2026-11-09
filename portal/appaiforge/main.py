"""Aplicação FastAPI + NiceGUI do portal."""

import hmac
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
    from . import telemetry

    telemetry.configure("appaiforge-portal")

    application = FastAPI(title="AIDB", version=__version__)
    get_engine()
    Base.metadata.create_all(get_engine())  # Alembic é o caminho normal; create_all garante dev/boot
    _seed_demo_admin()

    from .services.catalog import ensure_presets

    ensure_presets()

    from .services import litellm_sync

    litellm_sync.sync_all()

    from .agent_queue import reconcile_orphaned_runs

    reconcile_orphaned_runs()

    @application.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @application.get("/internal/inference/context")
    def inference_context_endpoint(request: Request, system_id: str) -> JSONResponse:
        """Contexto de inferência para o broker (autenticado por token de serviço)."""
        from .config import get_settings
        from .services.systems import inference_context

        expected = get_settings().inference_broker_service_token
        supplied = request.headers.get("x-aidb-broker-token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return JSONResponse({"error": "não autorizado"}, status_code=401)
        context = inference_context(system_id)
        if context is None:
            return JSONResponse({"error": "sistema não encontrado"}, status_code=404)
        return JSONResponse(context)

    @application.post("/internal/db-gate/audit")
    async def db_gate_audit(request: Request) -> JSONResponse:
        """Modo sombra (task 6.1): classifica e audita sem segurar nada —
        confirmável/bloqueada aqui não impedem a execução, só registram pra
        comparação com os globs do harness (spike S5, task 6.2).

        `enforced=true` no payload (fechamento de lacuna, roteiro de teste
        manual): o proxy já recusou de verdade em modo enforce — vira
        auditoria de "bloqueada", não "sombra"."""
        from .config import get_settings
        from . import gate

        expected = get_settings().db_gate_proxy_service_token
        supplied = request.headers.get("x-aidb-dbgate-token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return JSONResponse({"error": "não autorizado"}, status_code=401)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - payload inválido não deve derrubar o portal
            return JSONResponse({"error": "payload inválido"}, status_code=400)
        system_id = payload.get("system_id")
        sql = payload.get("sql")
        origin = payload.get("origin")
        if not system_id or not sql or origin not in ("agente", "app"):
            return JSONResponse(
                {"error": "system_id, sql e origin ('agente' ou 'app') são obrigatórios"}, status_code=400
            )
        gate_class = gate.record_shadow_decision(
            system_id, sql, origin=origin, connection_name=payload.get("connection_name", ""),
            enforced=bool(payload.get("enforced", False)),
        )
        return JSONResponse({"classification": gate_class.value})

    @application.post("/internal/inference/usage")
    async def inference_usage_endpoint(request: Request) -> JSONResponse:
        """Callback de uso do LiteLLM (idempotente por id de evento)."""
        from .config import get_settings
        from .services.inference_usage import record_usage

        expected = get_settings().inference_broker_service_token
        supplied = request.headers.get("x-aidb-broker-token") or request.query_params.get("token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return JSONResponse({"error": "não autorizado"}, status_code=401)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - payload inválido não deve derrubar o portal
            return JSONResponse({"error": "payload inválido"}, status_code=400)
        try:
            recorded = record_usage(payload)
        except Exception:  # noqa: BLE001 - FK/uso não atribuível
            return JSONResponse({"error": "uso não registrado"}, status_code=422)
        return JSONResponse({"recorded": recorded})

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
    ui.run_with(application, title="AIDB")
    return application


app = create_app()
