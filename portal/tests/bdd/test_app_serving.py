"""Steps BDD de app-serving: acesso verificado pelo edge e identidade por app (change add-oidc-sso).

Exercita o endpoint de forwardAuth do portal e o template canônico que as guidelines
mandam copiar para a app gerada (appaiforge.app_template.identity).
"""

from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth, security
from appaiforge.app_template.identity import verify_identity
from appaiforge.db import session_scope
from appaiforge.edge_auth import IDENTITY_HEADER, router
from appaiforge.models import System, SystemStatus
from appaiforge.services.directory import add_member, create_group, link_group_to_system
from appaiforge.services.systems import create_system

scenarios("features/app_serving.feature")

_ctx: dict = {}


def _edge(path: str, token: str | None):
    slug = path.split("/")[2]
    client = TestClient(_ctx["app"])
    if token:
        client.cookies.set(auth.COOKIE_NAME, token)
    return client.get(f"/internal/edge/auth/{slug}", headers={"X-Forwarded-Uri": path}, follow_redirects=False)


@given(parsers.parse('um sistema "{slug}" ativo com um membro de grupo vinculado'))
def sistema_ativo(clean_db, slug):
    _ctx.clear()
    owner = auth.create_user("dono@bdd.local", "pw", "editor")
    auth.create_user("membro@bdd.local", "pw", "app_user")
    auth.create_user("avulso@bdd.local", "pw", "app_user")
    system = create_system(owner, name=slug.upper(), slug=slug)
    with session_scope() as s:
        row = s.get(System, system.id)
        row.status = SystemStatus.active
        _ctx["secret"] = row.identity_secret
    create_group("equipe")
    add_member("equipe", "membro@bdd.local")
    link_group_to_system("equipe", slug)
    app = FastAPI()
    app.include_router(router)
    _ctx["app"] = app
    _ctx["slug"] = slug


@when(parsers.parse('o membro abre "{path}" logado no portal'))
def membro_abre(path):
    r = _edge(path, auth.authenticate("membro@bdd.local", "pw"))
    assert r.status_code == 200
    _ctx["claims"] = verify_identity(_ctx["secret"], _ctx["slug"], r.headers[IDENTITY_HEADER])


@then("a app reconhece o membro pelo identificador, tipo e grupos")
def app_reconhece():
    claims = _ctx["claims"]
    assert claims is not None
    assert claims["email"] == "membro@bdd.local" and claims["sub"]
    assert claims["user_type"] == "app_user" and claims["groups"] == ["equipe"]


@when(parsers.parse('chega à app "{slug}" uma identidade emitida para a app "{other}"'))
def identidade_de_outra_app(slug, other):
    token = security.sign_app_identity_jwt(_ctx["secret"], other, {"sub": "u", "user_type": "admin"}, 60)
    _ctx["claims"] = verify_identity(_ctx["secret"], slug, token)


@when("chega à app uma identidade expirada")
def identidade_expirada():
    token = security.sign_app_identity_jwt(_ctx["secret"], _ctx["slug"], {"sub": "u", "user_type": "admin"}, -3600)
    _ctx["claims"] = verify_identity(_ctx["secret"], _ctx["slug"], token)


@then("a app recusa a identidade")
def app_recusa():
    assert _ctx["claims"] is None


@when(parsers.parse('alguém sem sessão abre "{path}"'))
def sem_sessao(path):
    _ctx["resp"] = _edge(path, None)


@then(parsers.parse('é levado ao login com retorno a "{path}"'))
def levado_ao_login(path):
    r = _ctx["resp"]
    assert r.status_code == 302
    loc = urlsplit(r.headers["location"])
    assert loc.path == "/login" and parse_qs(loc.query)["next"] == [path]


@when(parsers.parse('um usuário sem vínculo abre "{path}"'))
def sem_vinculo(path):
    _ctx["resp"] = _edge(path, auth.authenticate("avulso@bdd.local", "pw"))


@then("o portal recusa com permissão insuficiente")
def recusa():
    assert _ctx["resp"].status_code == 403 and "Permissão insuficiente" in _ctx["resp"].text
