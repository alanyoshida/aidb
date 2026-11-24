"""Feature BDD: portal-identity — login, tipos globais e visibilidade.

Cada cenário deriva de um `#### Scenario` da spec; convenção D13/ADR 0016.
"""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth
from appaiforge.auth import LoginRejected
from appaiforge.models import System, SystemStatus
from appaiforge.rbac import visible_system_ids
from appaiforge.services.directory import add_member, create_group, link_group_to_system
from appaiforge.services.systems import NotPermitted, create_system

scenarios("features/portal_identity.feature")

_results: dict = {}
_ctx: dict = {}


# --- Login / logout ---

@given("um usuário ativo registrado com e-mail e senha")
def usuario_registrado(clean_db):
    auth.create_user("editor@test.local", "senha-ok", "editor")
    _results.clear()


@when(parsers.parse("ele autentica com e-mail \"{email}\" e senha \"{password}\""))
def ele_autentica(email, password):
    try:
        _results["token"] = auth.authenticate(email, password)
        _results["erro"] = None
    except LoginRejected:
        _results["token"] = None
        _results["erro"] = "rejected"


@then("uma sessão é iniciada com sucesso")
def sessao_iniciada():
    assert _results["erro"] is None
    assert _results["token"]


@then("o login é rejeitado sem revelar qual campo falhou")
def login_rejeitado():
    assert _results["erro"] == "rejected"


@when("ele encerra a sessão")
def ele_encerra():
    auth.logout(_results["token"])


@then("requisições posteriores com aquela sessão são recusadas")
def sessao_invalidada():
    assert auth.resolve_user(_results["token"]) is None


# --- Tipos globais de usuário ---

def _mk(email: str, user_type: str):
    return auth.create_user(email, "pw", user_type)


@given(parsers.parse('um usuário do tipo "{user_type}" autenticado'))
def usuario_do_tipo(clean_db, user_type):
    _ctx["user"] = _mk(f"{user_type.replace('_', '')}@vis.local", user_type)


@when(parsers.parse('ele cria um sistema com nome "{name}" e slug "{slug}"'))
def ele_cria_sistema(name, slug):
    try:
        _ctx["system"] = create_system(_ctx["user"], name, slug)
        _ctx["erro"] = None
    except NotPermitted:
        _ctx["system"] = None
        _ctx["erro"] = "not_permitted"


@then(parsers.parse('o sistema é criado no estado "{status}" com ele como dono'))
def sistema_criado(status):
    assert _ctx["erro"] is None
    system: System = _ctx["system"]
    assert system.status == SystemStatus(status)
    assert system.owner_id == _ctx["user"].id


@then("a criação é recusada por permissão insuficiente")
def criacao_recusada():
    assert _ctx["erro"] == "not_permitted"
    assert _ctx["system"] is None


# --- Visibilidade de sistemas ---

@given(parsers.parse('um sistema "{slug}" de um editor'))
def sistema_de_editor(clean_db, slug):
    editor = _mk(f"dono-{slug}@vis.local", "editor")
    _ctx[slug] = create_system(editor, slug.upper(), slug)


@given(parsers.parse('um "{user_type}" membro do grupo "{group}" vinculado ao sistema "{slug}"'))
def membro_de_grupo(clean_db, user_type, group, slug):
    user = _mk(f"{group}-{user_type}@vis.local", user_type)
    create_group(group)
    add_member(group, user.email)
    link_group_to_system(group, slug)
    _ctx["membro"] = user


@then(parsers.parse('o "{user_type}" enxerga o sistema "{slug}"'))
def enxerga(user_type, slug):
    assert _ctx[slug].id in visible_system_ids(_ctx["membro"])


@then(parsers.parse('um "app_user" sem vínculo não enxerga o sistema "{slug}"'))
def sem_vinculo_nao_enxerga(clean_db, slug):
    other = _mk("avulso@vis.local", "app_user")
    assert _ctx[slug].id not in visible_system_ids(other)


# --- Retorno ao destino após o login ---

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from appaiforge.auth_routes import rate_limiter, router

    rate_limiter.reset()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@when(parsers.parse('ele abre "{path}" sem sessão e é levado ao login'))
def abre_sem_sessao(path):
    from urllib.parse import parse_qs, urlsplit

    from appaiforge.auth_routes import login_url

    url = login_url(path)
    _ctx["next"] = parse_qs(urlsplit(url).query).get("next", ["/"])[0]


@when(parsers.parse('o login é iniciado com destino "{target}"'))
def login_com_destino(target):
    _ctx["next"] = target


@when("ele entra pelo formulário de login")
def entra_pelo_formulario():
    r = _client().post(
        "/auth/local",
        json={"email": "editor@test.local", "password": "senha-ok", "next": _ctx["next"]},
    )
    assert r.status_code == 200
    _ctx["destino"] = r.json()["next"]


@then(parsers.parse('ele chega a "{path}"'))
def chega_a(path):
    assert _ctx["destino"] == path


# --- Administração no modo OIDC ---

@given(parsers.parse('o portal no modo "{mode}" com um admin break-glass'))
def portal_no_modo(mode, clean_db, monkeypatch):
    from appaiforge.config import get_settings
    from appaiforge.security import hash_password
    from appaiforge.services.directory import sync_breakglass

    monkeypatch.setenv("APPAIFORGE_AUTH_MODE", mode)
    monkeypatch.setenv("APPAIFORGE_BREAKGLASS_EMAIL", "bg@t.local")
    monkeypatch.setenv("APPAIFORGE_BREAKGLASS_PASSWORD_HASH", hash_password("pw"))
    get_settings.cache_clear()
    sync_breakglass()
    _ctx.clear()
    _ctx["admin"] = auth.resolve_principal(auth.authenticate("bg@t.local", "pw"))


@given("um usuário que já entrou pelo IdP")
def usuario_do_idp():
    from appaiforge.oidc import upsert_shadow_user
    from appaiforge.models import UserType

    upsert_shadow_user("sub-1", "sso@corp.example", UserType.app_user, [])


@then("o admin não consegue criar, alterar tipo, desativar nem excluir usuários")
def admin_nao_gerencia_usuarios():
    from appaiforge.services import directory

    admin = _ctx["admin"]
    for op in (
        lambda: directory.create_user_as_admin("novo@t.local", "pw", "editor", actor=admin),
        lambda: directory.update_user_type("sso@corp.example", "admin", admin),
        lambda: directory.set_user_active("sso@corp.example", False, actor=admin),
        lambda: directory.delete_user("sso@corp.example", admin),
    ):
        with pytest.raises(directory.ManagedByIdp):
            op()


@then("o admin não consegue adicionar nem remover membros de grupos")
def admin_nao_gerencia_membros():
    from appaiforge.services import directory

    admin = _ctx["admin"]
    directory.create_group("g1", actor=admin)
    with pytest.raises(directory.ManagedByIdp):
        directory.add_member("g1", "sso@corp.example", actor=admin)
    with pytest.raises(directory.ManagedByIdp):
        directory.remove_member("g1", "sso@corp.example", admin)


@when(parsers.parse('o admin cadastra o grupo "{group}" e o vincula ao sistema "{slug}"'))
def admin_cadastra_e_vincula(group, slug):
    create_group(group, actor=_ctx["admin"])
    link_group_to_system(group, slug, actor=_ctx["admin"])


def _principal_com_grupos(groups):
    from appaiforge.auth import Principal
    from appaiforge.models import UserType
    from appaiforge.oidc import upsert_shadow_user

    uid = upsert_shadow_user(f"sub-{groups[0]}", f"{groups[0].lower()}-{len(_ctx)}@corp.example",
                             UserType.app_user, list(groups))
    _ctx[f"u-{groups[0]}"] = uid
    return Principal(id=uid, email="x", type=UserType.app_user, theme="light-indigo", active=True,
                     auth_method="oidc", break_glass=False, group_names=tuple(groups))


@then(parsers.parse('um usuário cujo token traz o grupo "{group}" acessa o sistema "{slug}"'))
def token_acessa(group, slug):
    from appaiforge.rbac import can_access_system

    assert can_access_system(_principal_com_grupos([group]), _ctx[slug].id)


@then(parsers.parse('um usuário cujo token traz o grupo "{group}" não acessa o sistema "{slug}"'))
def token_nao_acessa(group, slug):
    from appaiforge.rbac import can_access_system

    assert not can_access_system(_principal_com_grupos([group]), _ctx[slug].id)


@given(parsers.parse('o grupo "{group}" foi visto em um token'))
def grupo_visto(group):
    from appaiforge.models import UserType
    from appaiforge.oidc import upsert_shadow_user

    upsert_shadow_user("sub-visto", "visto@corp.example", UserType.app_user, [group])


@then(parsers.parse('o portal sugere "{group}" ao cadastrar grupo'))
def portal_sugere(group):
    from appaiforge.services.directory import suggested_group_names

    assert group in suggested_group_names()


@then(parsers.parse('cadastrar "{group}" mostra o aviso de grupo sem usuários'))
def aviso_grupo_novo(group):
    from appaiforge.services.directory import group_name_hint

    assert "Nenhum usuário" in (group_name_hint(group) or "")


@then(parsers.parse('cadastrar "{group}" não mostra aviso'))
def sem_aviso_grupo(group):
    from appaiforge.services.directory import group_name_hint

    assert group_name_hint(group) is None


@then("renomear grupo mostra o aviso de nome idêntico ao do IdP")
def aviso_renomear():
    from appaiforge.services.directory import rename_warning

    assert "idêntico" in (rename_warning() or "")


@then("renomear grupo não mostra aviso")
def sem_aviso_renomear():
    from appaiforge.services.directory import rename_warning

    assert rename_warning() is None


# --- Capacidade de DB Manager (change add-db-manager-role) ---

def _reload(email: str):
    from sqlalchemy import select

    from appaiforge.db import session_scope
    from appaiforge.models import User

    with session_scope() as s:
        user = s.execute(select(User).where(User.email == email)).scalar_one()
        s.expunge(user)
        return user


@given(parsers.parse('um usuário do tipo "{user_type}" que é DB Manager'))
def usuario_db_manager(clean_db, user_type):
    from appaiforge.db import session_scope
    from appaiforge.models import User

    user = _mk(f"{user_type.replace('_', '')}-dba@vis.local", user_type)
    with session_scope() as s:
        s.get(User, user.id).db_manager = True
    _ctx["user"] = _reload(user.email)


@then("ele pode gerir o catálogo de conexões")
def pode_gerir_catalogo():
    from appaiforge.rbac import can_manage_catalog

    assert can_manage_catalog(_ctx["user"])


@then("ele não pode gerir o catálogo de conexões")
def nao_pode_gerir_catalogo():
    from appaiforge.rbac import can_manage_catalog

    assert not can_manage_catalog(_ctx["user"])


@then("ele não pode usar o chat de geração")
def nao_pode_chat():
    from appaiforge.rbac import can_chat

    assert not can_chat(_ctx["user"])


@given(parsers.parse('um admin no modo local e um usuário "{email}" do tipo "{user_type}"'))
def admin_e_usuario(clean_db, email, user_type):
    _ctx.clear()
    _ctx["admin"] = _mk("boss@t.local", "admin")
    _mk(email, user_type)


@when(parsers.parse('o admin marca "{email}" como DB Manager'))
def admin_marca(email):
    from appaiforge.services import directory

    directory.set_db_manager(email, True, _ctx["admin"])


@when(parsers.parse('o admin retira de "{email}" a capacidade de DB Manager'))
def admin_retira(email):
    from appaiforge.services import directory

    directory.set_db_manager(email, False, _ctx["admin"])


@then(parsers.parse('"{email}" pode gerir o catálogo e continua do tipo "{user_type}"'))
def pode_e_continua(email, user_type):
    from appaiforge.rbac import can_manage_catalog

    user = _reload(email)
    assert can_manage_catalog(user) and user.type.value == user_type


@then(parsers.parse('"{email}" não pode gerir o catálogo'))
def nao_pode_mais(email):
    from appaiforge.rbac import can_manage_catalog

    assert not can_manage_catalog(_reload(email))


@then(parsers.parse('"{email}" não consegue conceder a capacidade a outro usuário'))
def nao_concede(email):
    from appaiforge.services import directory

    _mk("outro@t.local", "editor")
    with pytest.raises(PermissionError):
        directory.set_db_manager("outro@t.local", True, _reload(email))


@given("um usuário que entrou pelo IdP com o papel de DB Manager")
def usuario_idp_dba():
    from appaiforge.models import UserType
    from appaiforge.oidc import upsert_shadow_user

    upsert_shadow_user("sub-dba", "dba@corp.example", UserType.editor, [], db_manager=True)


@then("a lista de usuários mostra que ele é DB Manager")
def lista_mostra_dba():
    from appaiforge.services import directory

    rows = {u["email"]: u for u in directory.list_users_overview()}
    assert rows["dba@corp.example"]["db_manager"] is True


@then("o admin não consegue conceder nem retirar a capacidade")
def admin_nao_concede_oidc():
    from appaiforge.services import directory

    for value in (True, False):
        with pytest.raises(directory.ManagedByIdp):
            directory.set_db_manager("dba@corp.example", value, _ctx["admin"])
