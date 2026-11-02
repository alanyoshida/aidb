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
