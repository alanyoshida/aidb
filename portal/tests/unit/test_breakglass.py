"""Admin break-glass (change add-oidc-sso, tasks 3.2/3.3; spec portal-identity)."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from appaiforge import auth
from appaiforge.auth_routes import rate_limiter, router
from appaiforge.config import get_settings
from appaiforge.db import session_scope
from appaiforge.models import ManagementAudit, Session as DbSession, User, UserType, utcnow
from appaiforge.security import hash_password
from appaiforge.services import directory
from appaiforge.services.directory import ProtectedUser, sync_breakglass

BG = "bg@emergencia.local"


@pytest.fixture()
def breakglass(clean_db, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_BREAKGLASS_EMAIL", BG)
    monkeypatch.setenv("APPAIFORGE_BREAKGLASS_PASSWORD_HASH", hash_password("emergencia"))
    get_settings.cache_clear()
    sync_breakglass()
    rate_limiter.reset()
    with session_scope() as s:
        return s.execute(select(User).where(User.email == BG)).scalar_one().id


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _audit_actions() -> list[str]:
    with session_scope() as s:
        return list(s.execute(select(ManagementAudit.action).order_by(ManagementAudit.created_at)).scalars())


def test_env_presente_cria_admin_break_glass(breakglass):
    with session_scope() as s:
        user = s.get(User, breakglass)
        assert user.type == UserType.admin and user.break_glass and user.active


def test_env_removida_desativa_e_apaga_sessoes(breakglass, monkeypatch):
    token = auth.authenticate(BG, "emergencia")
    monkeypatch.setenv("APPAIFORGE_BREAKGLASS_EMAIL", "")
    get_settings.cache_clear()
    sync_breakglass()
    assert auth.resolve_principal(token) is None
    with pytest.raises(auth.LoginRejected):
        auth.authenticate(BG, "emergencia")


def test_operacoes_de_admin_sobre_break_glass_sao_recusadas(breakglass):
    directory.create_group("ops")
    for op in (
        lambda: directory.set_user_active(BG, False),
        lambda: directory.update_user_type(BG, "app_user", actor=_admin()),
        lambda: directory.delete_user(BG, actor=_admin()),
        lambda: directory.add_member("ops", BG),
    ):
        with pytest.raises(ProtectedUser):
            op()


def _admin():
    with session_scope() as s:
        u = s.execute(select(User).where(User.email == "adm@t.local")).scalar_one_or_none()
        if u:
            s.expunge(u)
            return u
    return auth.create_user("adm@t.local", "pw", "admin")


def test_break_glass_entra_no_modo_oidc_e_e_auditado(breakglass, client, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_AUTH_MODE", "oidc")
    get_settings.cache_clear()
    r = client.post("/auth/local", json={"email": BG, "password": "emergencia"})
    assert r.status_code == 200
    p = auth.resolve_principal(r.cookies.get(auth.COOKIE_NAME))
    assert p.is_admin and p.break_glass and p.auth_method == "break_glass"
    assert "Max-Age=28800" in r.headers["set-cookie"]
    assert _audit_actions() == ["breakglass_login"]


def test_senha_errada_e_auditada(breakglass, client):
    r = client.post("/auth/local", json={"email": BG, "password": "errada"})
    assert r.status_code == 401
    assert _audit_actions() == ["breakglass_login_failed"]


def test_bloqueio_apos_cinco_falhas_mesmo_com_senha_certa(breakglass, client):
    for _ in range(5):
        assert client.post("/auth/local", json={"email": BG, "password": "x"}).status_code == 401
    r = client.post("/auth/local", json={"email": BG, "password": "emergencia"})
    assert r.status_code == 429 and r.json()["error"] == "bloqueado"
    # outro e-mail do mesmo IP não é afetado
    auth.create_user("ed@t.local", "pw", "editor")
    assert client.post("/auth/local", json={"email": "ed@t.local", "password": "pw"}).status_code == 200


def test_sessao_de_emergencia_expira_em_8h(breakglass):
    token = auth.authenticate(BG, "emergencia")
    with session_scope() as s:
        sess = s.execute(select(DbSession).where(DbSession.user_id == breakglass)).scalar_one()
        assert sess.expires_at - utcnow() <= timedelta(hours=8)
        sess.expires_at = utcnow() - timedelta(seconds=1)
    assert auth.resolve_principal(token) is None
