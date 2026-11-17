"""Rotas HTTP de autenticação (change add-oidc-sso, D2/D3/D7).

Login e logout são rotas FastAPI — não handlers NiceGUI — para poder devolver
`Set-Cookie` HttpOnly. As rotas OIDC (`/auth/login`, `/auth/callback`) ficam em
`oidc.py` e reaproveitam `set_session_cookie`/`safe_next` daqui.
"""

import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import auth, telemetry
from .config import get_settings

router = APIRouter()
_log = telemetry.get_logger()


def safe_next(raw: str | None) -> str:
    """Destino pós-login restrito ao próprio portal: caminho relativo começando com
    uma única `/`. Qualquer outra coisa (URL absoluta, `//host`, `/\\host`, esquema)
    vira a raiz — evita open redirect (requirement "Retorno ao destino após o login")."""
    if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    if "\\" in raw or any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return "/"
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return "/"
    return raw


def login_url(next_path: str | None) -> str:
    target = safe_next(next_path)
    return "/login" if target == "/" else f"/login?next={quote(target, safe='')}"


def _cookie_secure() -> bool:
    return get_settings().public_base_url.startswith("https://")


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=max_age, path="/", httponly=True,
        samesite="lax", secure=_cookie_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(auth.COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=_cookie_secure())


def client_ip(request: Request) -> str:
    """IP do cliente atrás do Traefik (que regrava X-Forwarded-For de clientes não confiáveis)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


class LoginRateLimiter:
    """N falhas por (IP, e-mail) dentro da janela bloqueiam novas tentativas até a falha
    mais antiga sair da janela. Em memória: o portal roda em réplica única (D7)."""

    def __init__(self) -> None:
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: tuple[str, str], now: float) -> deque[float]:
        window = get_settings().login_rate_limit_window_seconds
        q = self._failures[key]
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def blocked(self, ip: str, email: str) -> bool:
        with self._lock:
            q = self._prune((ip, email), time.monotonic())
            return len(q) >= get_settings().login_rate_limit_attempts

    def record_failure(self, ip: str, email: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune((ip, email), now).append(now)

    def reset(self, ip: str | None = None, email: str | None = None) -> None:
        with self._lock:
            if ip is None:
                self._failures.clear()
            else:
                self._failures.pop((ip, email or ""), None)


rate_limiter = LoginRateLimiter()


def _audit_breakglass(email: str, ok: bool, ip: str, user_id: str | None = None) -> None:
    from .services import audit

    audit.record(
        actor_id=user_id, actor_email=email,
        action="breakglass_login" if ok else "breakglass_login_failed",
        resource_type="session", resource_id=None, details={"ip": ip},
    )


@router.post("/auth/local")
async def login_local(request: Request) -> JSONResponse:
    """Login por e-mail e senha (modo local; no modo oidc, só o break-glass)."""
    from .services.directory import is_breakglass_email

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - corpo inválido é só um login falho
        payload = {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    target = safe_next(payload.get("next"))
    ip = client_ip(request)
    breakglass = is_breakglass_email(email)

    if rate_limiter.blocked(ip, email):
        if breakglass:
            _audit_breakglass(email, False, ip)
        return JSONResponse({"ok": False, "error": "bloqueado"}, status_code=429)
    try:
        token = auth.authenticate(email, password)
    except auth.LoginRejected:
        rate_limiter.record_failure(ip, email)
        if breakglass:
            _audit_breakglass(email, False, ip)
        return JSONResponse({"ok": False, "error": "credenciais"}, status_code=401)

    principal = auth.resolve_principal(token)
    if principal is not None and principal.break_glass:
        _audit_breakglass(email, True, ip, principal.id)
    max_age = (
        get_settings().breakglass_session_hours * 3600 if breakglass
        else get_settings().session_ttl_days * 86400
    )
    response = JSONResponse({"ok": True, "next": target})
    set_session_cookie(response, token, max_age)
    return response


@router.get("/auth/logout")
def logout(request: Request) -> RedirectResponse:
    """Encerra a sessão do portal; sessões oidc seguem para o logout do IdP (D2)."""
    token = request.cookies.get(auth.COOKIE_NAME)
    id_token_enc = auth.end_session(token)
    target = "/login"
    if id_token_enc:
        from . import oidc

        target = oidc.end_session_url(id_token_enc) or target
    response = RedirectResponse(target, status_code=302)
    clear_session_cookie(response)
    return response
