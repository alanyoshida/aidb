"""Login OIDC contra um IdP fake (change add-oidc-sso, tasks 4.1–4.4; spec oidc-authentication).

O IdP fake responde discovery/JWKS/token por `httpx.MockTransport` e assina tokens
RS256 com uma chave gerada no teste — exercita validação real de assinatura,
emissor, audiência, nonce, PKCE e rotação de refresh token.
"""

import base64
import hashlib
import threading
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from sqlalchemy import select

from appaiforge import auth, oidc
from appaiforge.auth_routes import rate_limiter
from appaiforge.auth_routes import router as auth_router
from appaiforge.config import get_settings
from appaiforge.db import session_scope
from appaiforge.models import ObservedIdpGroup, Session as DbSession, User, UserType, utcnow
from appaiforge.security import encrypt_secret

ISSUER = "http://idp.public:8180/realms/aidb"
INTERNAL = "http://idp.internal:8080"
CLIENT_ID = "aidb-portal"
PUBLIC = "http://portal.test"


class FakeIdp:
    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)
        self.codes: dict[str, dict] = {}
        self.refresh: dict[str, dict] = {}  # refresh token -> perfil do usuário (mutável)
        self.hosts: list[str] = []
        self.token_calls = 0
        self.down = False
        self.lock = threading.Lock()

    # perfil: {"sub", "email", "roles", "groups"}
    def _tokens(self, profile: dict, nonce: str | None, iss: str = ISSUER, aud: str = CLIENT_ID,
                key=None, exp_delta: int = 300) -> dict:
        now = int(time.time())
        key = key or self.key
        hdr = {"alg": "RS256", "kid": key.kid}
        idc = {"iss": iss, "aud": aud, "sub": profile["sub"], "email": profile["email"],
               "exp": now + exp_delta, "iat": now}
        if nonce is not None:
            idc["nonce"] = nonce
        acc = {"iss": iss, "sub": profile["sub"], "email": profile["email"], "exp": now + exp_delta,
               "realm_access": {"roles": profile["roles"]}, "groups": profile["groups"]}
        rt = f"rt-{len(self.refresh)}-{profile['sub']}"
        self.refresh[rt] = profile
        return {"id_token": jwt.encode(hdr, idc, key), "access_token": jwt.encode(hdr, acc, key),
                "refresh_token": rt, "token_type": "Bearer"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.hosts.append(request.url.host)
        if self.down:
            raise httpx.ConnectError("idp fora do ar")
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
                "token_endpoint": ISSUER + "/protocol/openid-connect/token",
                "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
                "end_session_endpoint": ISSUER + "/protocol/openid-connect/logout",
            })
        if path.endswith("/certs"):
            return httpx.Response(200, json=KeySet([self.key]).as_dict(private=False))
        if path.endswith("/token"):
            with self.lock:
                self.token_calls += 1
                form = parse_qs(request.content.decode())
                grant = form["grant_type"][0]
                if grant == "authorization_code":
                    entry = self.codes.pop(form["code"][0], None)
                    if entry is None:
                        return httpx.Response(400, json={"error": "invalid_grant"})
                    challenge = base64.urlsafe_b64encode(
                        hashlib.sha256(form["code_verifier"][0].encode()).digest()
                    ).rstrip(b"=").decode()
                    if challenge != entry["challenge"]:
                        return httpx.Response(400, json={"error": "invalid_grant", "d": "pkce"})
                    return httpx.Response(200, json=entry.get("override") or self._tokens(entry["profile"], entry["nonce"]))
                rt = form["refresh_token"][0]
                profile = self.refresh.pop(rt, None)  # rotação: refresh token de uso único
                if profile is None or profile.get("disabled"):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                time.sleep(0.05)
                return httpx.Response(200, json=self._tokens(profile, None))
        return httpx.Response(404)


@pytest.fixture()
def idp(clean_db, monkeypatch):
    env = {
        "APPAIFORGE_AUTH_MODE": "oidc",
        "APPAIFORGE_OIDC_ISSUER": ISSUER,
        "APPAIFORGE_OIDC_CLIENT_ID": CLIENT_ID,
        "APPAIFORGE_OIDC_CLIENT_SECRET": "segredo",
        "APPAIFORGE_OIDC_INTERNAL_BASE_URL": INTERNAL,
        "APPAIFORGE_PUBLIC_BASE_URL": PUBLIC,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    oidc.reset_cache()
    rate_limiter.reset()
    fake = FakeIdp()
    monkeypatch.setattr(oidc, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)))
    return fake


@pytest.fixture()
def client(idp):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(oidc.router)
    return TestClient(app, base_url=PUBLIC)


def _start(client, next_path="/"):
    r = client.get("/auth/login", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return {k: v[0] for k, v in q.items()}, r


def _login(client, idp, profile, next_path="/", override=None):
    params, _ = _start(client, next_path)
    idp.codes["c1"] = {"profile": profile, "nonce": params["nonce"], "challenge": params["code_challenge"],
                       "override": override}
    return client.get("/auth/callback", params={"code": "c1", "state": params["state"]}, follow_redirects=False)


def _profile(**kw):
    base = {"sub": "sub-ana", "email": "ana@corp.example", "roles": ["editor"], "groups": ["financeiro"]}
    base.update(kw)
    return base


# --- 4.1 validação de tokens ------------------------------------------------

def test_discovery_e_jwks_usam_a_base_interna(idp, client):
    _start(client)
    assert set(idp.hosts) == {"idp.internal"}


@pytest.mark.parametrize("bad", ["iss", "aud", "nonce", "signature", "expired"])
def test_id_token_invalido_e_recusado(idp, bad):
    profile = _profile()
    kwargs = {"iss": {"iss": "http://outro/realms/x"}, "aud": {"aud": "outro-client"},
              "signature": {"key": RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)},
              "expired": {"exp_delta": -120}}.get(bad, {})
    tokens = idp._tokens(profile, "nonce-certo", **kwargs)
    with pytest.raises(oidc.OidcError):
        oidc.validate_id_token(tokens["id_token"], "nonce-errado" if bad == "nonce" else "nonce-certo")


def test_id_token_valido(idp):
    tokens = idp._tokens(_profile(), "n1")
    assert oidc.validate_id_token(tokens["id_token"], "n1")["sub"] == "sub-ana"


# --- 4.2 login e callback ---------------------------------------------------

def test_login_sso_bem_sucedido(idp, client):
    r = _login(client, idp, _profile(), next_path="/apps/erp/relatorios")
    assert r.status_code == 302 and r.headers["location"] == "/apps/erp/relatorios"
    assert "HttpOnly" in r.headers["set-cookie"]
    p = auth.resolve_principal(r.cookies.get(auth.COOKIE_NAME))
    assert p.type == UserType.editor and p.group_names == ("financeiro",) and p.auth_method == "oidc"
    with session_scope() as s:
        user = s.execute(select(User).where(User.idp_subject == "sub-ana")).scalar_one()
        assert user.email == "ana@corp.example" and user.password_hash is None
        assert s.get(ObservedIdpGroup, "financeiro") is not None


def test_authorize_usa_pkce_s256_e_redirect_publico(idp, client):
    params, r = _start(client)
    assert r.headers["location"].startswith(ISSUER + "/protocol/openid-connect/auth?")
    assert params["code_challenge_method"] == "S256" and params["redirect_uri"] == PUBLIC + "/auth/callback"
    assert "HttpOnly" in r.headers["set-cookie"] and "Path=/auth" in r.headers["set-cookie"]


def test_state_invalido_nao_cria_sessao(idp, client):
    params, _ = _start(client)
    idp.codes["c1"] = {"profile": _profile(), "nonce": params["nonce"], "challenge": params["code_challenge"]}
    r = client.get("/auth/callback", params={"code": "c1", "state": "forjado"}, follow_redirects=False)
    assert r.headers["location"] == "/login?erro=falha"
    assert auth.COOKIE_NAME not in r.cookies
    with session_scope() as s:
        assert s.execute(select(DbSession)).first() is None


def test_callback_sem_tentativa_no_navegador(idp, client):
    r = client.get("/auth/callback", params={"code": "c1", "state": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/login?erro=falha"


def test_erro_devolvido_pelo_idp(idp, client):
    params, _ = _start(client)
    r = client.get("/auth/callback", params={"error": "access_denied", "state": params["state"]},
                   follow_redirects=False)
    assert r.headers["location"] == "/login?erro=falha"


def test_sem_papel_reconhecido(idp, client):
    r = _login(client, idp, _profile(roles=["offline_access", "uma_authorization"]))
    assert r.headers["location"] == "/login?erro=acesso_negado"
    with session_scope() as s:
        assert s.execute(select(DbSession)).first() is None


def test_varios_papeis_prevalece_o_maior(idp, client):
    r = _login(client, idp, _profile(roles=["app_user", "admin"]))
    assert auth.resolve_principal(r.cookies.get(auth.COOKIE_NAME)).type == UserType.admin


def test_login_seguinte_atualiza_o_mesmo_usuario(idp, client):
    _login(client, idp, _profile())
    r = _login(client, idp, _profile(email="ana.silva@corp.example", roles=["app_user"]))
    p = auth.resolve_principal(r.cookies.get(auth.COOKIE_NAME))
    with session_scope() as s:
        users = s.execute(select(User)).scalars().all()
        assert len(users) == 1 and users[0].email == "ana.silva@corp.example"
        assert users[0].type == UserType.app_user
    assert p.id == users[0].id


def test_conflito_de_email_recusa(idp, client):
    _login(client, idp, _profile())
    r = _login(client, idp, _profile(sub="sub-outro"))
    assert r.headers["location"] == "/login?erro=falha"


def test_pkce_errado_recusado(idp, client):
    params, _ = _start(client)
    idp.codes["c1"] = {"profile": _profile(), "nonce": params["nonce"], "challenge": "outro"}
    r = client.get("/auth/callback", params={"code": "c1", "state": params["state"]}, follow_redirects=False)
    assert r.headers["location"] == "/login?erro=falha"


# --- 4.3 revalidação --------------------------------------------------------

def _logged(client, idp, profile):
    r = _login(client, idp, profile)
    token = r.cookies.get(auth.COOKIE_NAME)
    return token


def _expire_revalidation(token, by=timedelta(seconds=1)):
    with session_scope() as s:
        sess = s.get(DbSession, auth._token_fingerprint(token))
        sess.revalidate_at = utcnow() - by


def test_papel_trocado_no_idp_vale_na_revalidacao(idp, client):
    profile = _profile()
    token = _logged(client, idp, profile)
    profile["roles"] = ["app_user"]
    profile["groups"] = []
    _expire_revalidation(token)
    p = auth.resolve_principal(token)
    assert p.type == UserType.app_user and p.group_names == ()


def test_usuario_desativado_no_idp_encerra_sessao(idp, client):
    profile = _profile()
    token = _logged(client, idp, profile)
    profile["disabled"] = True
    _expire_revalidation(token)
    assert auth.resolve_principal(token) is None
    with session_scope() as s:
        assert s.get(DbSession, auth._token_fingerprint(token)) is None


def test_papel_removido_encerra_sessao(idp, client):
    profile = _profile()
    token = _logged(client, idp, profile)
    profile["roles"] = []
    _expire_revalidation(token)
    assert auth.resolve_principal(token) is None


def test_revalidacao_concorrente_gasta_um_unico_refresh(idp, client):
    token = _logged(client, idp, _profile())
    _expire_revalidation(token)
    calls_before = idp.token_calls
    results: list = []

    def resolve():
        results.append(auth.resolve_principal(token))

    threads = [threading.Thread(target=resolve) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r is not None for r in results)
    assert idp.token_calls - calls_before == 1


def test_idp_fora_do_ar_dentro_e_alem_da_tolerancia(idp, client):
    token = _logged(client, idp, _profile())
    idp.down = True
    _expire_revalidation(token, by=timedelta(seconds=10))
    assert auth.resolve_principal(token) is not None  # dentro dos 60 s de tolerância
    _expire_revalidation(token, by=timedelta(seconds=120))
    assert auth.resolve_principal(token) is None  # fail-closed


# --- 4.4 logout federado ----------------------------------------------------

def test_logout_redireciona_ao_idp_com_id_token_hint(idp, client):
    token = _logged(client, idp, _profile())
    client.cookies.set(auth.COOKIE_NAME, token)
    r = client.get("/auth/logout", follow_redirects=False)
    loc = urlsplit(r.headers["location"])
    q = parse_qs(loc.query)
    assert r.headers["location"].startswith(ISSUER + "/protocol/openid-connect/logout?")
    assert q["post_logout_redirect_uri"] == [PUBLIC + "/login"] and q["id_token_hint"][0]
    assert auth.resolve_principal(token) is None


def test_auth_login_no_modo_local_volta_para_o_formulario(clean_db, monkeypatch):
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(oidc.router)
    r = TestClient(app).get("/auth/login", params={"next": "/apps/x"}, follow_redirects=False)
    assert r.headers["location"] == "/login?next=%2Fapps%2Fx"


def test_end_session_url_sem_idp(idp):
    idp.down = True
    assert oidc.end_session_url(encrypt_secret("x")) is None
