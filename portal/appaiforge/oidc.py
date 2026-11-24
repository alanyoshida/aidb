"""Login SSO por OpenID Connect (capability oidc-authentication; change add-oidc-sso D2/D4/D5).

Fluxo authorization code com PKCE contra um IdP externo (Keycloak no E2E):

    /auth/login?next=  -> cookie de tentativa cifrado (state, nonce, verifier, next)
                       -> 302 authorization_endpoint
    /auth/callback     -> confere state, troca code por tokens, valida ID/access token
                       -> papel + grupos do token -> usuário-sombra (sub) -> sessão
    revalidate_session -> refresh_token grant periódico (lazy, com lock de linha)
    end_session_url    -> logout federado (end_session_endpoint + id_token_hint)

Emissor público x interno (D11): o `iss` é validado contra `oidc_issuer` (endereço que o
navegador usa); quando `oidc_internal_base_url` está definido, só as chamadas
servidor-a-servidor (discovery, token, JWKS) são reescritas para a base interna.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from sqlalchemy import select

from . import auth, telemetry
from .auth_routes import login_url, safe_next, set_session_cookie
from .config import get_settings
from .db import session_scope
from .models import ObservedIdpGroup, Session as DbSession, User, UserType, utcnow
from .security import decrypt_secret, encrypt_secret

router = APIRouter()
_log = telemetry.get_logger()

ATTEMPT_COOKIE = "aidb_oidc_attempt"
ATTEMPT_TTL_SECONDS = 600
_ROLE_RANK = {"app_user": 1, "editor": 2, "admin": 3}
# Papel que concede a capacidade de DB Manager (change add-db-manager-role, D2): lido no mesmo
# claim de papéis, fora da ordem de tipos — sozinho não define tipo nem permite entrar.
DB_MANAGER_ROLE = "db_manager"
_HTTP_TIMEOUT = 5.0


class OidcError(Exception):
    """Falha de protocolo/validação; a UI mostra só uma mensagem genérica."""


class AccessNotGranted(OidcError):
    """Usuário autenticado no IdP sem nenhum papel reconhecido."""


class IdpUnavailable(OidcError):
    """IdP inalcançável ou respondendo erro de servidor (não é recusa da sessão)."""


# --- HTTP e metadados do IdP -------------------------------------------------

# Fábrica do cliente HTTP; os testes trocam por um httpx.Client com MockTransport.
def _http_client() -> httpx.Client:
    return httpx.Client(timeout=_HTTP_TIMEOUT)


_cache_lock = threading.Lock()
_cache: dict = {}


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _internal(url: str) -> str:
    """Reescreve uma URL pública do IdP para a base interna (chamadas servidor-a-servidor)."""
    internal = get_settings().oidc_internal_base_url.rstrip("/")
    if not internal:
        return url
    parts = urlsplit(url)
    rest = url[len(f"{parts.scheme}://{parts.netloc}"):]
    return internal + rest


def _discovery() -> dict:
    with _cache_lock:
        cached = _cache.get("discovery")
    if cached and cached[0] > time.time():
        return cached[1]
    issuer = get_settings().oidc_issuer.rstrip("/")
    url = _internal(issuer + "/.well-known/openid-configuration")
    try:
        with _http_client() as http:
            resp = http.get(url)
    except httpx.HTTPError as exc:
        raise IdpUnavailable(f"discovery inalcançável: {exc}") from exc
    if resp.status_code != 200:
        raise IdpUnavailable(f"discovery respondeu {resp.status_code}")
    meta = resp.json()
    with _cache_lock:
        _cache["discovery"] = (time.time() + 3600, meta)
    return meta


def _jwks(force: bool = False) -> KeySet:
    with _cache_lock:
        cached = _cache.get("jwks")
    if cached and not force:
        return cached
    try:
        with _http_client() as http:
            resp = http.get(_internal(_discovery()["jwks_uri"]))
    except httpx.HTTPError as exc:
        raise IdpUnavailable(f"JWKS inalcançável: {exc}") from exc
    if resp.status_code != 200:
        raise IdpUnavailable(f"JWKS respondeu {resp.status_code}")
    keys = KeySet.import_key_set(resp.json())
    with _cache_lock:
        _cache["jwks"] = keys
    return keys


def _decode(token: str) -> dict:
    """Valida a assinatura (JWKS do IdP, recarregado uma vez se o kid for novo)."""
    for attempt in (False, True):
        try:
            return jwt.decode(token, _jwks(force=attempt), algorithms=["RS256", "ES256", "PS256"]).claims
        except JoseError as exc:
            if attempt:
                raise OidcError(f"assinatura inválida: {exc}") from exc
        except ValueError as exc:  # kid desconhecido / token malformado
            if attempt:
                raise OidcError(f"token inválido: {exc}") from exc
    raise OidcError("token inválido")  # pragma: no cover


def validate_id_token(id_token: str, nonce: str) -> dict:
    s = get_settings()
    claims = _decode(id_token)
    registry = jwt.JWTClaimsRegistry(
        iss={"essential": True, "value": s.oidc_issuer.rstrip("/")},
        aud={"essential": True, "value": s.oidc_client_id},
        exp={"essential": True},
        sub={"essential": True},
        nonce={"essential": True, "value": nonce},
    )
    try:
        registry.validate(claims)
    except JoseError as exc:
        raise OidcError(f"ID token recusado: {exc}") from exc
    return claims


def validate_access_token(access_token: str) -> dict:
    claims = _decode(access_token)
    registry = jwt.JWTClaimsRegistry(
        iss={"essential": True, "value": get_settings().oidc_issuer.rstrip("/")},
        exp={"essential": True},
    )
    try:
        registry.validate(claims)
    except JoseError as exc:
        raise OidcError(f"access token recusado: {exc}") from exc
    return claims


# --- Mapeamento de claims (D4) ---------------------------------------------

def _claim_path(claims: dict, path: str):
    node = claims
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def map_user_type(claims: dict) -> UserType:
    """Maior papel reconhecido (admin > editor > app_user); nenhum -> AccessNotGranted."""
    roles = _claim_path(claims, get_settings().oidc_roles_claim) or []
    if isinstance(roles, str):
        roles = [roles]
    known = [r for r in roles if r in _ROLE_RANK]
    if not known:
        raise AccessNotGranted("nenhum papel reconhecido no token")
    return UserType(max(known, key=_ROLE_RANK.__getitem__))


def map_db_manager(claims: dict) -> bool:
    """True quando o claim de papéis traz `db_manager`."""
    roles = _claim_path(claims, get_settings().oidc_roles_claim) or []
    if isinstance(roles, str):
        roles = [roles]
    return DB_MANAGER_ROLE in roles


def map_groups(*claim_sets: dict) -> list[str]:
    """Nomes de grupo do primeiro conjunto de claims que os trouxer, sem duplicatas."""
    path = get_settings().oidc_groups_claim
    for claims in claim_sets:
        raw = _claim_path(claims, path)
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = [raw]
        return sorted({str(g) for g in raw if g})
    return []


def _record_observed(s, groups: list[str]) -> None:
    now = utcnow()
    for name in groups:
        row = s.get(ObservedIdpGroup, name)
        if row is None:
            s.add(ObservedIdpGroup(name=name, last_seen_at=now))
        else:
            row.last_seen_at = now


def upsert_shadow_user(
    sub: str, email: str, user_type: UserType, groups: list[str], db_manager: bool = False,
) -> str:
    """Usuário-sombra pelo `sub`: cria no primeiro login, atualiza e-mail e tipo depois.

    E-mail já usado por outro usuário (outro `sub` ou o break-glass) -> OidcError: não há
    vínculo automático por e-mail (troca de modo não é suportada)."""
    email = (email or "").strip().lower()
    if not email:
        raise OidcError("token sem e-mail")
    with session_scope() as s:
        user = s.execute(select(User).where(User.idp_subject == sub)).scalar_one_or_none()
        clash = s.execute(
            select(User).where(User.email == email, User.idp_subject.is_distinct_from(sub))
        ).scalar_one_or_none()
        if clash is not None:
            raise OidcError(f"e-mail {email} já pertence a outro usuário")
        if user is None:
            user = User(idp_subject=sub, email=email, type=user_type, password_hash=None, db_manager=db_manager)
            s.add(user)
        else:
            user.email = email
            user.type = user_type
            user.db_manager = db_manager
        _record_observed(s, groups)
        s.flush()
        if not user.active:
            raise OidcError("usuário desativado no portal")
        return user.id


# --- Rotas ---------------------------------------------------------------------

def _redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + "/auth/callback"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _fail(reason: str, error_key: str = "falha") -> RedirectResponse:
    _log.info("login oidc recusado", extra={"result": "falha", "reason": reason})
    response = RedirectResponse(f"/login?erro={error_key}", status_code=302)
    response.delete_cookie(ATTEMPT_COOKIE, path="/auth")
    return response


@router.get("/auth/login")
def oidc_login(request: Request) -> RedirectResponse:
    from .auth_mode import is_oidc

    target = safe_next(request.query_params.get("next"))
    if not is_oidc():
        return RedirectResponse(login_url(target), status_code=302)
    try:
        meta = _discovery()
    except IdpUnavailable as exc:
        return _fail(str(exc))
    s = get_settings()
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    attempt = encrypt_secret(json.dumps({
        "state": state, "nonce": nonce, "verifier": verifier, "next": target,
        "exp": int(time.time()) + ATTEMPT_TTL_SECONDS,
    }))
    params = {
        "response_type": "code",
        "client_id": s.oidc_client_id,
        "redirect_uri": _redirect_uri(),
        "scope": s.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    response = RedirectResponse(meta["authorization_endpoint"] + "?" + urlencode(params), status_code=302)
    response.set_cookie(
        ATTEMPT_COOKIE, attempt, max_age=ATTEMPT_TTL_SECONDS, path="/auth", httponly=True,
        samesite="lax", secure=s.public_base_url.startswith("https://"),
    )
    return response


def _token_request(data: dict) -> httpx.Response:
    s = get_settings()
    url = _internal(_discovery()["token_endpoint"])
    try:
        with _http_client() as http:
            return http.post(url, data=data, auth=(s.oidc_client_id, s.oidc_client_secret))
    except httpx.HTTPError as exc:
        raise IdpUnavailable(f"token endpoint inalcançável: {exc}") from exc


def _read_attempt(request: Request) -> dict | None:
    raw = request.cookies.get(ATTEMPT_COOKIE)
    if not raw:
        return None
    try:
        attempt = json.loads(decrypt_secret(raw))
    except (InvalidToken, ValueError):
        return None
    if int(attempt.get("exp", 0)) < time.time():
        return None
    return attempt


@router.get("/auth/callback")
def oidc_callback(request: Request) -> RedirectResponse:
    q = request.query_params
    attempt = _read_attempt(request)
    if attempt is None or not secrets.compare_digest(q.get("state", ""), attempt["state"]):
        return _fail("state ausente ou divergente")
    if q.get("error"):
        return _fail(f"IdP devolveu erro: {q.get('error')}")
    code = q.get("code")
    if not code:
        return _fail("retorno sem code")
    try:
        resp = _token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
            "code_verifier": attempt["verifier"],
        })
        if resp.status_code != 200:
            raise OidcError(f"troca de code recusada ({resp.status_code})")
        tokens = resp.json()
        id_claims = validate_id_token(tokens.get("id_token", ""), attempt["nonce"])
        access_claims = validate_access_token(tokens.get("access_token", ""))
        user_type = map_user_type(access_claims)
        groups = map_groups(access_claims, id_claims)
        db_manager = map_db_manager(access_claims)
        user_id = upsert_shadow_user(
            id_claims["sub"], id_claims.get("email") or access_claims.get("email", ""), user_type, groups,
            db_manager=db_manager,
        )
    except AccessNotGranted as exc:
        return _fail(str(exc), "acesso_negado")
    except OidcError as exc:
        return _fail(str(exc))

    settings = get_settings()
    token = auth.create_session(
        user_id,
        auth_method="oidc",
        user_type=user_type.value,
        groups=groups,
        db_manager=db_manager,
        refresh_token_enc=encrypt_secret(tokens["refresh_token"]) if tokens.get("refresh_token") else None,
        id_token_enc=encrypt_secret(tokens["id_token"]),
        revalidate_at=utcnow() + timedelta(seconds=settings.oidc_revalidate_seconds),
    )
    _log.info("login oidc bem-sucedido", extra={"user_id": user_id, "result": "sucesso"})
    response = RedirectResponse(attempt["next"], status_code=302)
    response.delete_cookie(ATTEMPT_COOKIE, path="/auth")
    set_session_cookie(response, token, settings.session_ttl_days * 86400)
    return response


# --- Revalidação (D5) ---------------------------------------------------------

def revalidate_session(session_id: str) -> bool:
    """Refresh token grant sob lock da linha da sessão. Devolve False quando a sessão
    deve morrer (o IdP recusou, papel sumiu, ou o IdP ficou fora além da tolerância)."""
    settings = get_settings()
    with session_scope() as s:
        sess = s.execute(
            select(DbSession).where(DbSession.id == session_id).with_for_update()
        ).scalar_one_or_none()
        if sess is None:
            return False
        now = utcnow()
        if sess.revalidate_at is None or sess.revalidate_at > now:
            return True  # outra requisição já revalidou enquanto esperávamos o lock
        if not sess.refresh_token_enc:
            s.delete(sess)
            return False
        try:
            resp = _token_request({
                "grant_type": "refresh_token",
                "refresh_token": decrypt_secret(sess.refresh_token_enc),
            })
        except IdpUnavailable as exc:
            return _tolerate_outage(s, sess, now, settings, str(exc))
        if resp.status_code >= 500:
            return _tolerate_outage(s, sess, now, settings, f"token endpoint {resp.status_code}")
        if resp.status_code != 200:
            _log.info("revalidação recusada pelo IdP", extra={"user_id": sess.user_id, "status": resp.status_code})
            s.delete(sess)
            return False
        tokens = resp.json()
        try:
            access_claims = validate_access_token(tokens.get("access_token", ""))
            user_type = map_user_type(access_claims)
        except IdpUnavailable as exc:
            return _tolerate_outage(s, sess, now, settings, str(exc))
        except OidcError as exc:
            _log.info("revalidação sem papel/token válido", extra={"user_id": sess.user_id, "reason": str(exc)})
            s.delete(sess)
            return False
        groups = map_groups(access_claims)
        db_manager = map_db_manager(access_claims)
        sess.user_type = user_type.value
        sess.groups = groups
        sess.db_manager = db_manager
        if tokens.get("refresh_token"):
            sess.refresh_token_enc = encrypt_secret(tokens["refresh_token"])
        if tokens.get("id_token"):
            sess.id_token_enc = encrypt_secret(tokens["id_token"])
        sess.revalidate_at = now + timedelta(seconds=settings.oidc_revalidate_seconds)
        user = s.get(User, sess.user_id)
        if user is not None:
            user.type = user_type
            user.db_manager = db_manager
        _record_observed(s, groups)
        return True


def _tolerate_outage(s, sess, now, settings, reason: str) -> bool:
    if now > sess.revalidate_at + timedelta(seconds=settings.oidc_network_grace_seconds):
        _log.info("IdP indisponível além da tolerância; sessão encerrada", extra={"reason": reason})
        s.delete(sess)
        return False
    _log.info("IdP indisponível; sessão mantida dentro da tolerância", extra={"reason": reason})
    return True


auth.set_revalidator(revalidate_session)


# --- Logout federado ----------------------------------------------------------

def end_session_url(id_token_enc: str) -> str | None:
    settings = get_settings()
    try:
        endpoint = _discovery().get("end_session_endpoint")
        id_token = decrypt_secret(id_token_enc)
    except (IdpUnavailable, InvalidToken):
        return None
    if not endpoint:
        return None
    params = {
        "id_token_hint": id_token,
        "post_logout_redirect_uri": settings.public_base_url.rstrip("/") + "/login",
        "client_id": settings.oidc_client_id,
    }
    return endpoint + "?" + urlencode(params)
