"""Autenticação e sessões server-side (specs portal-identity, oidc-authentication).

O cookie guarda um token aleatório T; o banco guarda sha256(T) com expiração.
Logout apaga a sessão — requisições posteriores com o mesmo cookie são recusadas.
O cookie é HttpOnly e gravado por rotas HTTP (`/auth/local`, `/auth/callback`),
nunca por JavaScript (change add-oidc-sso, D3).

Toda requisição autenticada resolve um `Principal` — quem é o usuário nesta
requisição —, independente do modo de autenticação:
- modo local: tipo e grupos vêm do banco (`users.type`, `group_members`);
- modo oidc: tipo e grupos vêm do snapshot do token gravado na sessão e
  revalidado periodicamente junto ao IdP.
"""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from . import telemetry
from .config import get_settings
from .db import session_scope
from .models import Session as DbSession
from .models import User, UserType, utcnow
from .security import hash_password, verify_password

COOKIE_NAME = "appaiforge_session"

_log = telemetry.get_logger()


class LoginRejected(Exception):
    """Credenciais inválidas ou conta desativada — a UI trata com mensagem genérica."""


@dataclass(frozen=True)
class Principal:
    """Identidade efetiva da requisição. Expõe os mesmos atributos de `User` que as
    páginas e serviços usam, para circular no lugar dele.

    `group_names is None` significa "pertença a grupos pelo banco" (modo local);
    uma tupla é a lista de nomes de grupo vinda do token (modo oidc).
    """

    id: str
    email: str
    type: UserType
    theme: str
    active: bool
    auth_method: str
    break_glass: bool
    group_names: tuple[str, ...] | None
    session_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.type == UserType.admin

    @property
    def is_editor(self) -> bool:
        return self.type == UserType.editor


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    user_id: str,
    *,
    auth_method: str = "local",
    ttl: timedelta | None = None,
    user_type: str | None = None,
    groups: list[str] | None = None,
    refresh_token_enc: str | None = None,
    id_token_enc: str | None = None,
    revalidate_at: datetime | None = None,
) -> str:
    """Cria a sessão no banco e devolve o token do cookie (só o hash é persistido)."""
    token = secrets.token_urlsafe(32)
    with session_scope() as s:
        s.add(DbSession(
            id=_token_fingerprint(token),
            user_id=user_id,
            expires_at=utcnow() + (ttl or timedelta(days=get_settings().session_ttl_days)),
            auth_method=auth_method,
            user_type=user_type,
            groups=groups,
            refresh_token_enc=refresh_token_enc,
            id_token_enc=id_token_enc,
            revalidate_at=revalidate_at,
        ))
        user = s.get(User, user_id)
        if user is not None:
            user.last_login_at = utcnow()
    return token


def session_ttl_for(user: User) -> timedelta:
    if user.break_glass:
        return timedelta(hours=get_settings().breakglass_session_hours)
    return timedelta(days=get_settings().session_ttl_days)


def authenticate(email: str, password: str) -> str:
    """Valida credenciais locais e cria sessão; devolve o token do cookie.

    Levanta LoginRejected com motivo único para e-mail inexistente, senha
    errada ou conta desativada (não revelar qual campo falhou). No modo oidc,
    só o admin break-glass tem credencial local (spec oidc-authentication).
    """
    from .auth_mode import is_oidc

    normalized_email = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
        ok = (
            user is not None
            and user.active
            and user.password_hash
            and verify_password(password, user.password_hash)
            and (user.break_glass or not is_oidc())
        )
        if not ok:
            _log.info("tentativa de login falhou", extra={"email": normalized_email, "result": "falha"})
            raise LoginRejected()
        user_id, ttl = user.id, session_ttl_for(user)
        method = "break_glass" if user.break_glass else "local"
    _log.info("login bem-sucedido", extra={"email": normalized_email, "user_id": user_id, "result": "sucesso"})
    return create_session(user_id, auth_method=method, ttl=ttl)


# Revalidação de sessões oidc junto ao IdP; registrada por `oidc.py` (evita import
# circular). Recebe o id da sessão e devolve False quando a sessão deve morrer.
_revalidator: Callable[[str], bool] | None = None


def set_revalidator(fn: Callable[[str], bool] | None) -> None:
    global _revalidator
    _revalidator = fn


def resolve_principal(token: str | None) -> Principal | None:
    if not token:
        return None
    sid = _token_fingerprint(token)
    with session_scope() as s:
        sess = s.get(DbSession, sid)
        if sess is None or sess.expires_at < utcnow():
            return None
        needs_revalidation = (
            sess.auth_method == "oidc" and sess.revalidate_at is not None and sess.revalidate_at <= utcnow()
        )
    if needs_revalidation:
        if _revalidator is None or not _revalidator(sid):
            return None
    with session_scope() as s:
        sess = s.get(DbSession, sid)
        if sess is None:
            return None
        user = s.get(User, sess.user_id)
        if user is None or not user.active:
            return None
        if sess.auth_method == "oidc":
            user_type = UserType(sess.user_type)
            group_names: tuple[str, ...] | None = tuple(sess.groups or ())
        else:
            user_type = user.type
            group_names = None
        return Principal(
            id=user.id,
            email=user.email,
            type=user_type,
            theme=user.theme,
            active=user.active,
            auth_method=sess.auth_method,
            break_glass=user.break_glass,
            group_names=group_names,
            session_id=sid,
        )


# Nome histórico: as páginas e testes chamam `resolve_user`; devolve um Principal.
resolve_user = resolve_principal


def end_session(token: str | None) -> str | None:
    """Apaga a sessão; devolve o id_token cifrado (sessões oidc) para o logout federado."""
    if not token:
        return None
    with session_scope() as s:
        sess = s.get(DbSession, _token_fingerprint(token))
        if sess is None:
            return None
        id_token_enc = sess.id_token_enc
        s.delete(sess)
        return id_token_enc


def logout(token: str | None) -> None:
    end_session(token)


def create_user(email: str, password: str, user_type: str) -> User:
    with session_scope() as s:
        user = User(
            email=email.strip().lower(),
            password_hash=hash_password(password),
            type=UserType(user_type),
        )
        s.add(user)
        s.flush()
        s.expunge(user)
        return user
