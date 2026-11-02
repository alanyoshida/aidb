"""Template canônico de identidade para as apps geradas (ADR 0006).

As guidelines mandam o agente copiar este módulo para a app gerada. O portal
redireciona para `/apps/<slug>/?t=<token>`; a app valida e estabelece sessão
própria. Token inválido/expirado -> `resolve_identity` devolve None (a UI da
app manda o usuário de volta ao portal, que reautentica).
"""

import base64
import hashlib
import hmac
import json
import time


def resolve_identity(secret: str, token: str, now: float | None = None) -> dict | None:
    """Payload {user_id, user_type, exp} se o token for válido; None caso contrário."""
    try:
        body_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        current = now if now is not None else time.time()
        if int(payload.get("exp", 0)) < current:
            return None
        if "user_id" not in payload or "user_type" not in payload:
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def install_identity(app, secret: str) -> None:
    """Middleware NiceGUI/FastAPI: troca ?t= por sessão da app (app.storage.user).

    Uso na app gerada (com ui.run(storage_secret=...)):

        from nicegui import app, ui
        from identity import install_identity
        install_identity(app, os.environ["APP_IDENTITY_SECRET"])
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class IdentityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            token = request.query_params.get("t")
            if token:
                payload = resolve_identity(secret, token)
                if payload is None:
                    return _redirect_portal(request)
                request.session["identity"] = payload
                return _redirect_clean(request)
            return await call_next(request)

    app.add_middleware(IdentityMiddleware)


def _redirect_portal(request):
    from starlette.responses import RedirectResponse

    return RedirectResponse("/", status_code=302)


def _redirect_clean(request):
    from starlette.responses import RedirectResponse

    from urllib.parse import urlencode

    params = {k: v for k, v in request.query_params.items() if k != "t"}
    target = request.path
    if params:
        target += "?" + urlencode(params)
    return RedirectResponse(target, status_code=302)
