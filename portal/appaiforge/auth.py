"""Autenticação local e sessões server-side (spec portal-identity).

O cookie guarda um token aleatório T; o banco guarda sha256(T) com expiração.
Logout apaga a sessão — requisições posteriores com o mesmo cookie são recusadas.
O cookie é setado via JavaScript (ui.run_javascript) porque os handlers do
NiceGUI não devolvem um Response; aceitável neste portal interno (sem HttpOnly).
"""

import hashlib
import secrets
from datetime import timedelta

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


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(email: str, password: str) -> str:
    """Valida credenciais e cria sessão; devolve o token do cookie.

    Levanta LoginRejected com motivo único para e-mail inexistente, senha
    errada ou conta desativada (não revelar qual campo falhou).
    """
    normalized_email = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == normalized_email)).scalar_one_or_none()
        if user is None or not user.active or not verify_password(password, user.password_hash):
            _log.info("tentativa de login falhou", extra={"email": normalized_email, "result": "falha"})
            raise LoginRejected()
        token = secrets.token_urlsafe(32)
        sess = DbSession(
            id=_token_fingerprint(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=get_settings().session_ttl_days),
        )
        s.add(sess)
        _log.info("login bem-sucedido", extra={"email": normalized_email, "user_id": user.id, "result": "sucesso"})
        return token


def resolve_user(token: str | None) -> User | None:
    if not token:
        return None
    with session_scope() as s:
        sess = s.get(DbSession, _token_fingerprint(token))
        if sess is None or sess.expires_at < utcnow():
            return None
        user = s.get(User, sess.user_id)
        if user is None or not user.active:
            return None
        s.expunge(user)
        return user


def logout(token: str | None) -> None:
    if not token:
        return
    with session_scope() as s:
        sess = s.get(DbSession, _token_fingerprint(token))
        if sess is not None:
            s.delete(sess)


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
