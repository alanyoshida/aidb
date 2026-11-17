"""Acesso às apps pelo edge e identidade por app (change add-oidc-sso, tasks 6.1–6.4; spec app-serving)."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey

from appaiforge import auth, security
from appaiforge.app_template.identity import verify_identity
from appaiforge.db import session_scope
from appaiforge.edge import app_route_config
from appaiforge.edge_auth import IDENTITY_HEADER, router
from appaiforge.models import System, SystemStatus
from appaiforge.services.directory import add_member, create_group, link_group_to_system
from appaiforge.services.systems import create_system


@pytest.fixture()
def env(clean_db):
    owner = auth.create_user("dono@t.local", "pw", "editor")
    member = auth.create_user("membro@t.local", "pw", "app_user")
    outsider = auth.create_user("fora@t.local", "pw", "app_user")
    system = create_system(owner, name="ERP", slug="erp")
    other = create_system(owner, name="RH", slug="rh")
    with session_scope() as s:
        for sid in (system.id, other.id):
            s.get(System, sid).status = SystemStatus.active
    create_group("financeiro")
    add_member("financeiro", "membro@t.local")
    link_group_to_system("financeiro", "erp")
    app = FastAPI()
    app.include_router(router)
    tokens = {u: auth.authenticate(f"{u}@t.local", "pw") for u in ("dono", "membro", "fora")}
    with session_scope() as s:
        secrets = {sid: s.get(System, sid).identity_secret for sid in (system.id, other.id)}
    return {"client": TestClient(app), "tokens": tokens, "erp": system, "rh": other,
            "secret": secrets[system.id], "rh_secret": secrets[other.id]}


def _call(env, who, uri="/apps/erp/relatorios?mes=3", slug="erp", extra=None):
    cookies = {auth.COOKIE_NAME: env["tokens"][who]} if who else {}
    headers = {"X-Forwarded-Uri": uri, **(extra or {})}
    client = env["client"]
    client.cookies.clear()
    for k, v in cookies.items():
        client.cookies.set(k, v)
    return client.get(f"/internal/edge/auth/{slug}", headers=headers, follow_redirects=False)


# --- 6.1 desfechos do forwardAuth -----------------------------------------------

def test_sem_sessao_vai_ao_login_com_retorno_a_app(env):
    r = _call(env, None)
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert urlsplit(r.headers["location"]).path == "/login"
    assert q["next"] == ["/apps/erp/relatorios?mes=3"]


def test_uri_fora_da_app_volta_para_a_raiz_da_app(env):
    r = _call(env, None, uri="https://evil.example/x")
    assert parse_qs(urlsplit(r.headers["location"]).query)["next"] == ["/apps/erp/"]


def test_sem_acesso_recebe_403(env):
    r = _call(env, "fora")
    assert r.status_code == 403 and "Permissão insuficiente" in r.text
    assert IDENTITY_HEADER not in r.headers


def test_membro_recebe_identidade_da_app(env):
    r = _call(env, "membro")
    assert r.status_code == 200
    claims = verify_identity(env["secret"], "erp", r.headers[IDENTITY_HEADER])
    assert claims["email"] == "membro@t.local" and claims["user_type"] == "app_user"
    assert claims["groups"] == ["financeiro"] and claims["aud"] == "aidb-app:erp"
    assert claims["iss"] == "aidb-portal" and claims["exp"] - time.time() <= 60
    assert r.headers["cache-control"] == "no-store"


def test_identidade_forjada_pelo_cliente_e_substituida(env):
    forged = security.sign_app_identity_jwt(env["secret"], "erp", {"sub": "x", "user_type": "admin"}, 60)
    r = _call(env, "membro", extra={IDENTITY_HEADER: forged})
    assert r.headers[IDENTITY_HEADER] != forged
    assert verify_identity(env["secret"], "erp", r.headers[IDENTITY_HEADER])["user_type"] == "app_user"
    # e a config do Traefik copia o header da resposta do portal (sobrescrevendo o do cliente)
    mw = app_route_config("erp")["http"]["middlewares"]["app-erp-auth"]["forwardAuth"]
    assert mw["authResponseHeaders"] == [IDENTITY_HEADER]


def test_logout_alcanca_a_app_na_requisicao_seguinte(env):
    assert _call(env, "membro").status_code == 200
    auth.logout(env["tokens"]["membro"])
    assert _call(env, "membro").status_code == 302


def test_acesso_revogado_alcanca_a_app(env):
    from appaiforge.services.directory import unlink_group_from_system

    assert _call(env, "membro").status_code == 200
    unlink_group_from_system("financeiro", "erp", auth.create_user("adm@t.local", "pw", "admin"))
    assert _call(env, "membro").status_code == 403


def test_sistema_inexistente_ou_inativo(env):
    assert _call(env, "dono", slug="nao-existe", uri="/apps/nao-existe/").status_code == 403


# --- 6.2 rotas do edge ------------------------------------------------------------

def test_rota_docker_tem_forwardauth_antes_do_strip(env):
    cfg = app_route_config("erp")["http"]
    assert cfg["routers"]["app-erp"]["middlewares"] == ["app-erp-auth", "app-erp-strip"]
    assert cfg["middlewares"]["app-erp-auth"]["forwardAuth"]["address"] == (
        "http://portal:8080/internal/edge/auth/erp"
    )


def test_rota_kubernetes_equivalente():
    from appaiforge.drivers.kubernetes_driver import app_route_objects

    objs = dict((o["metadata"]["name"], o) for _, o in app_route_objects("ns", "appaiforge-erp", "erp", 8080))
    route = objs["appaiforge-erp"]["spec"]["routes"][0]
    assert [m["name"] for m in route["middlewares"]] == ["appaiforge-erp-auth", "appaiforge-erp-strip"]
    fa = objs["appaiforge-erp-auth"]["spec"]["forwardAuth"]
    assert fa["address"].endswith("/internal/edge/auth/erp") and fa["authResponseHeaders"] == [IDENTITY_HEADER]


# --- 6.3 template de identidade da app -------------------------------------------

def test_template_recusa_identidade_de_outra_app(env):
    token = security.sign_app_identity_jwt(env["rh_secret"], "rh", {"sub": "u", "user_type": "admin"}, 60)
    assert verify_identity(env["rh_secret"], "rh", token) is not None
    assert verify_identity(env["secret"], "erp", token) is None          # segredo de outro sistema
    same_secret_other_aud = security.sign_app_identity_jwt(env["secret"], "rh", {"sub": "u", "user_type": "admin"}, 60)
    assert verify_identity(env["secret"], "erp", same_secret_other_aud) is None  # audiência de outra app


def test_template_recusa_expirada_ausente_e_alg_none(env):
    expired = security.sign_app_identity_jwt(env["secret"], "erp", {"sub": "u", "user_type": "admin"}, -5)
    assert verify_identity(env["secret"], "erp", expired) is None
    assert verify_identity(env["secret"], "erp", None) is None
    assert verify_identity(env["secret"], "erp", "lixo") is None
    token = security.sign_app_identity_jwt(env["secret"], "erp", {"sub": "u", "user_type": "admin"}, 60)
    header, payload, _ = token.split(".")
    import base64

    none_header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    assert verify_identity(env["secret"], "erp", f"{none_header}.{payload}.") is None


def test_template_middleware_responde_401_sem_identidade(env):
    from appaiforge.app_template.identity import current_identity, install_identity

    app = FastAPI()
    install_identity(app, secret=env["secret"], slug="erp")

    @app.get("/")
    def index(request: __import__("fastapi").Request):
        return {"email": current_identity(request)["email"]}

    c = TestClient(app)
    assert c.get("/").status_code == 401
    token = security.sign_app_identity_jwt(env["secret"], "erp", {"sub": "u", "email": "a@b", "user_type": "app_user"}, 60)
    assert c.get("/", headers={IDENTITY_HEADER: token}).json() == {"email": "a@b"}


def test_jwt_e_hs256_padrao(env):
    token = security.sign_app_identity_jwt(env["secret"], "erp", {"sub": "u", "user_type": "app_user"}, 60)
    decoded = jwt.decode(token, OctKey.import_key(env["secret"]), algorithms=["HS256"])
    assert decoded.header["alg"] == "HS256" and decoded.claims["aud"] == "aidb-app:erp"


# --- 6.4 /entry legado ------------------------------------------------------------

def test_entry_legado_anexa_t_e_exige_login(env):
    client = env["client"]
    client.cookies.clear()
    r = client.get("/entry/erp", follow_redirects=False)
    assert r.headers["location"] == "/login?next=%2Fentry%2Ferp"
    client.cookies.set(auth.COOKIE_NAME, env["tokens"]["membro"])
    r = client.get("/entry/erp", follow_redirects=False)
    assert r.headers["location"].startswith("/apps/erp/?t=")
    t = parse_qs(urlsplit(r.headers["location"]).query)["t"][0]
    assert security.verify_identity_token(env["secret"], t)["email"] == "membro@t.local"


def test_redirect_ao_login_e_absoluto_no_host_original(env):
    # o Traefik resolveria um Location relativo contra o endereço interno do portal
    r = _call(env, None, extra={"X-Forwarded-Host": "localhost:8081", "X-Forwarded-Proto": "http"})
    assert r.headers["location"].startswith("http://localhost:8081/login?next=")


def test_redirect_usa_public_base_url_quando_configurada(env, monkeypatch):
    from appaiforge.config import get_settings

    monkeypatch.setenv("APPAIFORGE_PUBLIC_BASE_URL", "https://aidb.example.com")
    get_settings.cache_clear()
    r = _call(env, None, extra={"X-Forwarded-Host": "evil.example"})
    assert r.headers["location"].startswith("https://aidb.example.com/login?next=")
