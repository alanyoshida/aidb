"""Verificação de acesso às apps pelo edge — forwardAuth do Traefik (change add-oidc-sso, D8).

O Traefik chama `GET /internal/edge/auth/{slug}` antes de cada requisição a
`/apps/{slug}` (inclusive WebSocket), repassando os headers originais (o cookie de
sessão) e `X-Forwarded-Uri`:

    sem sessão válida -> 302 /login?next=<endereço da app>   (volta à app depois)
    sem acesso        -> 403
    ok                -> 200 + X-AIDB-Identity: <JWT da app>  (Traefik copia para a app)

Sem cache: cada requisição consulta sessão e acesso, para que logout e revogação
alcancem a app já na requisição seguinte. O handler é síncrono de propósito — o
FastAPI o roda no threadpool, e a revalidação oidc pode fazer uma chamada HTTP ao IdP.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import auth, security
from .auth_routes import login_url
from .config import get_settings

router = APIRouter()

IDENTITY_HEADER = "X-AIDB-Identity"

_FORBIDDEN_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Sem permissão</title></head><body style="font-family:sans-serif;margin:4rem auto;max-width:32rem">
<h1>Permissão insuficiente</h1>
<p>Sua conta não tem acesso a esta app. Peça acesso ao grupo responsável pelo sistema.</p>
<p><a href="/">Voltar ao portal</a></p></body></html>"""


def _original_uri(request: Request, slug: str) -> str:
    uri = request.headers.get("x-forwarded-uri") or ""
    prefix = f"/apps/{slug}"
    if uri == prefix or uri.startswith(prefix + "/") or uri.startswith(prefix + "?"):
        return uri
    return prefix + "/"


def _public_origin(request: Request) -> str:
    """Origem pública para o redirecionamento ao login. O Traefik resolve um `Location`
    relativo do forwardAuth contra o endereço INTERNO do portal (http://portal:8080), então
    o 302 precisa sair absoluto: `public_base_url` quando configurada, senão o host e o
    esquema originais que o Traefik repassa em X-Forwarded-Host/Proto."""
    configured = get_settings().public_base_url.rstrip("/")
    if configured:
        return configured
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    if not host or any(c in host for c in "/\\@ \r\n"):
        return ""
    return f"{proto if proto in ('http', 'https') else 'http'}://{host}"


def identity_claims(principal: auth.Principal) -> dict:
    from .rbac import group_names_of

    return {
        "sub": principal.id,
        "user_id": principal.id,
        "email": principal.email,
        "user_type": principal.type.value,
        "groups": group_names_of(principal),
    }


@router.get("/internal/edge/auth/{slug}")
def edge_auth(slug: str, request: Request) -> Response:
    from .models import SystemStatus
    from .rbac import can_access_system
    from .services.systems import get_system_by_slug

    principal = auth.resolve_principal(request.cookies.get(auth.COOKIE_NAME))
    if principal is None:
        return RedirectResponse(_public_origin(request) + login_url(_original_uri(request, slug)), status_code=302)
    system = get_system_by_slug(slug)
    if system is None or system.status != SystemStatus.active or not can_access_system(principal, system.id):
        return HTMLResponse(_FORBIDDEN_HTML, status_code=403)
    token = security.sign_app_identity_jwt(
        system.identity_secret, slug, identity_claims(principal),
        ttl_seconds=get_settings().identity_token_ttl_seconds,
    )
    return Response(status_code=200, headers={IDENTITY_HEADER: token, "Cache-Control": "no-store"})


@router.get("/entry/{slug}")
def app_entry(slug: str, request: Request) -> RedirectResponse:
    """Porta de entrada LEGADA da app (botão "Abrir app"; change add-oidc-sso, D9).

    O acesso a `/apps/{slug}` já é verificado pelo edge a cada requisição (forwardAuth)
    e a identidade chega à app no header `X-AIDB-Identity`. Este redirecionamento ainda
    anexa o token HMAC `?t=` só para que apps geradas antes dessa mudança — que só
    conhecem o handoff do ADR 0006 — continuem funcionando a partir do portal; apps
    novas ignoram `?t=`. Remover quando não houver mais apps antigas."""
    from .models import SystemStatus
    from .rbac import can_access_system
    from .services.systems import get_system_by_slug

    user = auth.resolve_principal(request.cookies.get(auth.COOKIE_NAME))
    if user is None:
        return RedirectResponse(login_url(f"/entry/{slug}"), status_code=302)
    system = get_system_by_slug(slug)
    if system is None or system.status != SystemStatus.active or not can_access_system(user, system.id):
        return RedirectResponse("/", status_code=302)
    token = security.sign_identity_token(
        system.identity_secret,
        {"user_id": user.id, "user_type": user.type.value, "email": user.email},
        ttl_seconds=get_settings().identity_token_ttl_seconds,
    )
    return RedirectResponse(f"/apps/{slug}/?t={token}", status_code=302)
