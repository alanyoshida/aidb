"""Feature BDD: db-connection-access — autorização, ativação com alias, teto e revogação.

Cada cenário deriva de um `#### Scenario` da spec; convenção D13/ADR 0016."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, User, UserType
from appaiforge.services import connections
from appaiforge.services.systems import create_system

scenarios("features/db_connection_access.feature")

_ctx: dict = {}


@pytest.fixture(autouse=True)
def _no_reprovision(monkeypatch):
    monkeypatch.setattr(connections, "_refresh_systems", lambda ids: None)


@given(parsers.parse('um DB Manager, o sistema "{slug}" de um editor e a conexão "{name}" no catálogo'))
def cenario_base(clean_db, slug, name):
    _ctx.clear()
    owner = auth.create_user("dono@bdd.local", "pw", UserType.editor.value)
    dba = auth.create_user("dba@bdd.local", "pw", UserType.app_user.value)
    with session_scope() as s:
        s.get(User, dba.id).db_manager = True
        conn = DbConnection(name=name, kind="postgres", host="db", port=5432, database="vendas",
                            username="app", password_encrypted="x")
        s.add(conn)
        s.flush()
        _ctx["conn"] = {name: conn.id}
    dba.db_manager = True
    _ctx.update(owner=owner, dba=dba, systems={slug: create_system(owner, slug.upper(), slug)})


def _grant_id(name: str, slug: str) -> str:
    system = _ctx["systems"][slug]
    return next(c["grant_id"] for c in connections.list_system_connections(system.id) if c["name"] == name)


@when(parsers.parse('o DB Manager autoriza "{name}" para o sistema "{slug}"'))
def autoriza(name, slug):
    connections.grant_connection(_ctx["conn"][name], _ctx["systems"][slug].id, actor=_ctx["dba"])


@when(parsers.parse('o dono ativa "{name}" no sistema "{slug}" com alias "{alias}" e modo "{mode}"'))
def ativa(name, slug, alias, mode):
    connections.activate(_ctx["systems"][slug], _grant_id(name, slug), alias, mode, actor=_ctx["owner"])


@when(parsers.parse('o DB Manager revoga "{name}" do sistema "{slug}"'))
def revoga(name, slug):
    connections.revoke_grant(_grant_id(name, slug), actor=_ctx["dba"])


@then(parsers.parse('a conexão "{name}" aparece disponível e inativa no sistema "{slug}"'))
def disponivel_inativa(name, slug):
    [view] = connections.list_system_connections(_ctx["systems"][slug].id)
    assert view["name"] == name and view["active"] is False


@then(parsers.parse('o agente do sistema "{slug}" não recebe nenhuma conexão'))
def nenhuma_conexao(slug):
    assert connections.active_connections(_ctx["systems"][slug].id) == []


@then(parsers.parse('o sistema "{slug}" recebe a conexão com alias "{alias}" no modo "{mode}"'))
def recebe(slug, alias, mode):
    [active] = connections.active_connections(_ctx["systems"][slug].id)
    assert (active.alias, active.mode) == (alias, mode)


@then(parsers.parse('ativar "{name}" no sistema "{slug}" em "{mode}" é recusado por estar acima do teto'))
def acima_do_teto(name, slug, mode):
    with pytest.raises(connections.InvalidMode, match="teto"):
        connections.activate(_ctx["systems"][slug], _grant_id(name, slug), "vendas", mode, actor=_ctx["owner"])


@then(parsers.parse('a aba de conexões do sistema "{slug}" mostra que "{alias}" foi revogada'))
def aviso_revogada(slug, alias):
    [notice] = connections.list_notices(_ctx["systems"][slug].id)
    assert notice["kind"] == "revoked" and notice["alias"] == alias
