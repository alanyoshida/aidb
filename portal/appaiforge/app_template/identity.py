"""Template canônico de identidade para as apps geradas (change add-oidc-sso, D9; substitui o
handoff `?t=` do ADR 0006).

As guidelines mandam o agente copiar este módulo para a app gerada. Só usa a biblioteca
padrão (a imagem base não ganha dependência).

Como funciona: o edge (Traefik) só deixa uma requisição chegar a `/apps/<slug>` depois
que o portal confirma a sessão e o acesso do usuário, e então injeta o header
`X-AIDB-Identity` — um JWT HS256 assinado com `APP_IDENTITY_SECRET` (segredo exclusivo
deste sistema), audiência `aidb-app:<slug>`, validade curta, com:

    {"sub", "user_id", "email", "user_type", "groups", "iss", "aud", "iat", "exp"}

A app valida o header EM TODA requisição e trata a identidade como o usuário daquela
requisição. Não guarde sessão própria: logout ou perda de acesso no portal valem na
requisição seguinte, porque o header deixa de vir.

Uso numa app NiceGUI/FastAPI:

    import os
    from fastapi import Request
    from nicegui import app, ui
    from identity import install_identity, current_identity

    install_identity(app)  # 401 para requisição sem identidade válida

    @ui.page("/")
    def index(request: Request):
        user = current_identity(request)  # {"email": ..., "user_type": ..., "groups": [...]}
        ui.label(f"Olá, {user['email']}")
"""

import base64
import hashlib
import hmac
import json
import os
import time

IDENTITY_HEADER = "X-AIDB-Identity"
ISSUER = "aidb-portal"


def _b64decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify_identity(secret: str, slug: str, token: str | None, now: float | None = None) -> dict | None:
    """Claims da identidade se o JWT for válido para ESTA app; None caso contrário.

    Confere algoritmo (só HS256), assinatura, emissor, audiência `aidb-app:<slug>`,
    expiração e presença de `sub`/`user_type`."""
    if not secret or not token:
        return None
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_b64decode(header_b64))
        if header.get("alg") != "HS256":
            return None
        expected = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(sig_b64)):
            return None
        claims = json.loads(_b64decode(payload_b64))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    current = now if now is not None else time.time()
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if claims.get("iss") != ISSUER or f"aidb-app:{slug}" not in audiences:
        return None
    if int(claims.get("exp", 0)) < current:
        return None
    if "sub" not in claims or "user_type" not in claims:
        return None
    return claims


def current_identity(request, secret: str | None = None, slug: str | None = None) -> dict | None:
    """Identidade validada da requisição (ou None)."""
    cached = getattr(getattr(request, "state", None), "identity", None)
    if cached is not None:
        return cached
    return verify_identity(
        secret if secret is not None else os.environ.get("APP_IDENTITY_SECRET", ""),
        slug if slug is not None else os.environ.get("APPAIFORGE_SLUG", ""),
        request.headers.get(IDENTITY_HEADER),
    )


def install_identity(app, secret: str | None = None, slug: str | None = None) -> None:
    """Middleware: recusa (401) toda requisição HTTP sem identidade válida e guarda a
    identidade em `request.state.identity`."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse

    key = secret if secret is not None else os.environ.get("APP_IDENTITY_SECRET", "")
    app_slug = slug if slug is not None else os.environ.get("APPAIFORGE_SLUG", "")

    class IdentityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            identity = verify_identity(key, app_slug, request.headers.get(IDENTITY_HEADER))
            if identity is None:
                return PlainTextResponse("AIDB: acesso restrito. Abra a app pelo portal.", status_code=401)
            request.state.identity = identity
            return await call_next(request)

    app.add_middleware(IdentityMiddleware)
