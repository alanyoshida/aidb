"""Principal, sessão e login local por rota HTTP (change add-oidc-sso, tasks 2.1/2.2)."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from appaiforge import auth
from appaiforge.auth_routes import login_url, rate_limiter, router, safe_next
from appaiforge.models import UserType


@pytest.fixture()
def client(clean_db):
    app = FastAPI()
    app.include_router(router)
    rate_limiter.reset()
    return TestClient(app)


# --- Principal (2.1) ---

def test_principal_local_vem_do_banco(clean_db):
    user = auth.create_user("ed@t.local", "pw", "editor")
    p = auth.resolve_principal(auth.authenticate("ed@t.local", "pw"))
    assert p.id == user.id and p.type == UserType.editor and p.is_editor
    assert p.group_names is None  # pertença pelo banco
    assert p.auth_method == "local" and not p.break_glass


def test_principal_oidc_vem_do_snapshot(clean_db):
    # usuário-sombra com tipo app_user persistido, mas o snapshot do token diz admin
    user = auth.create_user("sso@t.local", "pw", "app_user")
    token = auth.create_session(
        user.id, auth_method="oidc", user_type="admin", groups=["financeiro"],
        ttl=timedelta(hours=1),
    )
    p = auth.resolve_principal(token)
    assert p.type == UserType.admin and p.is_admin
    assert p.group_names == ("financeiro",)
    assert p.auth_method == "oidc"


def test_sessao_expirada_ou_usuario_inativo(clean_db):
    user = auth.create_user("x@t.local", "pw", "editor")
    expired = auth.create_session(user.id, ttl=timedelta(seconds=-1))
    assert auth.resolve_principal(expired) is None
    from appaiforge.services.directory import set_user_active

    token = auth.authenticate("x@t.local", "pw")
    set_user_active("x@t.local", False)
    assert auth.resolve_principal(token) is None


def test_login_local_recusado_no_modo_oidc_para_usuario_comum(clean_db, monkeypatch):
    auth.create_user("comum@t.local", "pw", "editor")
    monkeypatch.setenv("APPAIFORGE_AUTH_MODE", "oidc")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(auth.LoginRejected):
        auth.authenticate("comum@t.local", "pw")


# --- next saneado (2.2) ---

@pytest.mark.parametrize("raw,expected", [
    ("/systems/abc", "/systems/abc"),
    ("/apps/erp/relatorios?mes=3", "/apps/erp/relatorios?mes=3"),
    ("//evil.example", "/"),
    ("/\\evil.example", "/"),
    ("https://evil.example/x", "/"),
    ("javascript:alert(1)", "/"),
    ("", "/"),
    (None, "/"),
    ("/ok\r\nSet-Cookie: x", "/"),
])
def test_safe_next(raw, expected):
    assert safe_next(raw) == expected


def test_login_url_preserva_destino():
    assert login_url("/apps/erp/x?a=1") == "/login?next=%2Fapps%2Ferp%2Fx%3Fa%3D1"
    assert login_url("https://evil") == "/login"


# --- POST /auth/local (2.2) ---

def test_login_grava_cookie_httponly_e_devolve_next(client):
    auth.create_user("ed@t.local", "pw", "editor")
    r = client.post("/auth/local", json={"email": "ed@t.local", "password": "pw", "next": "/systems/1"})
    assert r.status_code == 200 and r.json() == {"ok": True, "next": "/systems/1"}
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith(f"{auth.COOKIE_NAME}=")
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie
    token = r.cookies.get(auth.COOKIE_NAME)
    assert auth.resolve_principal(token).email == "ed@t.local"


def test_login_com_next_externo_volta_para_raiz(client):
    auth.create_user("ed@t.local", "pw", "editor")
    r = client.post("/auth/local", json={"email": "ed@t.local", "password": "pw", "next": "//evil.example"})
    assert r.json()["next"] == "/"


def test_login_invalido_e_generico(client):
    auth.create_user("ed@t.local", "pw", "editor")
    for email, pw in (("ed@t.local", "errada"), ("nao@existe", "pw")):
        r = client.post("/auth/local", json={"email": email, "password": pw})
        assert r.status_code == 401 and r.json() == {"ok": False, "error": "credenciais"}
        assert "set-cookie" not in r.headers


def test_logout_apaga_sessao_e_cookie(client):
    auth.create_user("ed@t.local", "pw", "editor")
    r = client.post("/auth/local", json={"email": "ed@t.local", "password": "pw"})
    token = r.cookies.get(auth.COOKIE_NAME)
    r = client.get("/auth/logout", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    assert f'{auth.COOKIE_NAME}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert auth.resolve_principal(token) is None
