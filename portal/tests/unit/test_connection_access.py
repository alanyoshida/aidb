"""Unitários de autorização e ativação (change add-db-manager-role, grupo 4; spec
db-connection-access). As conexões são gravadas direto no catálogo, sem teste de rede, e o
reprovisionamento vira um registro em memória (`refreshes`)."""

import json

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnection, User, UserType
from appaiforge.rbac import can_access_system
from appaiforge.services import audit, connections, directory
from appaiforge.services.systems import create_system

SA_JSON = json.dumps({"type": "service_account", "client_email": "sa@proj.iam.gserviceaccount.com"})


@pytest.fixture()
def refreshes(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(connections, "_refresh_systems", lambda ids: calls.append(list(dict.fromkeys(ids))))
    return calls


@pytest.fixture()
def ctx(clean_db, refreshes):
    admin = auth.create_user("admin@acc.local", "pw", UserType.admin.value)
    owner = auth.create_user("dono@acc.local", "pw", UserType.editor.value)
    other = auth.create_user("outro@acc.local", "pw", UserType.editor.value)
    dba = auth.create_user("dba@acc.local", "pw", UserType.app_user.value)
    with session_scope() as s:
        s.get(User, dba.id).db_manager = True
    dba.db_manager = True
    x = create_system(owner, "Sistema X", "acc-x")
    y = create_system(other, "Sistema Y", "acc-y")
    z = create_system(other, "Sistema Z", "acc-z")
    return {"admin": admin, "owner": owner, "other": other, "dba": dba, "x": x, "y": y, "z": z}


def _conn(name="Vendas prod", kind="postgres") -> str:
    with session_scope() as s:
        conn = DbConnection(name=name, kind=kind, host="db", port=5432, database="vendas", username="app",
                            password_encrypted=connections.encrypt_secret(SA_JSON if kind == "bigquery" else "pw"))
        s.add(conn)
        s.flush()
        return conn.id


def _grant(ctx, conn_id, system, max_mode="read_write", **kw) -> str:
    return connections.grant_connection(conn_id, system.id, max_mode, actor=ctx["dba"], **kw)["grant_id"]


def _view(system, grant_id):
    return next(c for c in connections.list_system_connections(system.id) if c["grant_id"] == grant_id)


# --- Autorização de conexão por sistema ---

def test_autorizada_aparece_inativa(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    view = _view(ctx["x"], grant)
    assert view["active"] is False and view["name"] == "Vendas prod"
    assert connections.active_connections(ctx["x"].id) == []


def test_mesma_conexao_para_dois_sistemas_independentes(ctx):
    conn = _conn()
    gx = _grant(ctx, conn, ctx["x"], "read_only")
    gy = _grant(ctx, conn, ctx["y"], "read_write")
    assert _view(ctx["x"], gx)["max_mode"] == "read_only"
    assert _view(ctx["y"], gy)["max_mode"] == "read_write"


def test_autorizacao_duplicada_recusada(ctx):
    conn = _conn()
    _grant(ctx, conn, ctx["x"])
    with pytest.raises(connections.GrantExists):
        _grant(ctx, conn, ctx["x"])


def test_quem_nao_gere_o_catalogo_nao_autoriza(ctx):
    with pytest.raises(PermissionError):
        connections.grant_connection(_conn(), ctx["x"].id, actor=ctx["owner"])


def test_db_manager_autoriza_para_sistema_proprio(ctx):
    directory.set_db_manager(ctx["owner"].email, True, ctx["admin"])
    owner = auth.resolve_principal(auth.create_session(ctx["owner"].id))
    connections.grant_connection(_conn(), ctx["x"].id, actor=owner)
    assert len(connections.list_system_connections(ctx["x"].id)) == 1


# --- Sistemas visíveis ao autorizar ---

def test_db_manager_ve_todos_os_sistemas_so_com_nome_slug_e_dono(ctx):
    systems = connections.list_systems_for_grant()
    assert [s["slug"] for s in systems] == ["acc-x", "acc-y", "acc-z"]
    assert set(systems[0]) == {"id", "slug", "name", "owner_email"}
    assert systems[0]["owner_email"] == "dono@acc.local"


def test_db_manager_nao_entra_no_sistema_alheio(ctx):
    _grant(ctx, _conn(), ctx["x"])
    assert not can_access_system(ctx["dba"], ctx["x"].id)


# --- Teto de modo de acesso por autorização ---

def test_teto_padrao_read_write(ctx):
    grant = connections.grant_connection(_conn(), ctx["x"].id, actor=ctx["dba"])["grant_id"]
    assert _view(ctx["x"], grant)["max_mode"] == "read_write"


def test_elevar_teto_nao_muda_o_modo_vigente(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    connections.set_ceiling(grant, "schema_admin", actor=ctx["dba"])
    view = _view(ctx["x"], grant)
    assert view["max_mode"] == "schema_admin" and view["mode"] == "read_write"
    connections.set_mode(ctx["x"], grant, "schema_admin", actor=ctx["owner"])
    assert _view(ctx["x"], grant)["mode"] == "schema_admin"


def test_modo_desconhecido_recusado(ctx):
    with pytest.raises(connections.InvalidMode):
        _grant(ctx, _conn(), ctx["x"], "superuser")


# --- Modos de acesso disponíveis para BigQuery ---

def test_bigquery_sem_schema_admin(ctx):
    conn = _conn("BQ", "bigquery")
    with pytest.raises(connections.InvalidMode, match="BigQuery"):
        _grant(ctx, conn, ctx["x"], "schema_admin")
    grant = _grant(ctx, conn, ctx["x"], "read_write")
    assert _view(ctx["x"], grant)["modes"] == ["read_only", "read_write"]
    with pytest.raises(connections.InvalidMode, match="BigQuery"):
        connections.set_ceiling(grant, "schema_admin", actor=ctx["dba"])


# --- Ativação pelo dono do sistema ---

def test_dono_ativa_e_conexao_e_entregue(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_only", actor=ctx["owner"])
    [active] = connections.active_connections(ctx["x"].id)
    assert active.alias == "vendas" and active.mode == "read_only" and active.env_name == "VENDAS"
    assert refreshes == [[ctx["x"].id]]


def test_dono_desativa_e_autorizacao_continua(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    connections.deactivate(ctx["x"], grant, actor=ctx["owner"])
    assert connections.active_connections(ctx["x"].id) == []
    assert _view(ctx["x"], grant)["active"] is False
    assert refreshes[-1] == [ctx["x"].id]


def test_membro_de_grupo_nao_ativa(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    directory.create_group("time-x", actor=ctx["admin"])
    directory.add_member("time-x", ctx["other"].email, actor=ctx["admin"])
    directory.link_group_to_system("time-x", "acc-x", actor=ctx["admin"])
    assert can_access_system(ctx["other"], ctx["x"].id)
    with pytest.raises(PermissionError):
        connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["other"])


def test_admin_ativa_em_qualquer_sistema(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["admin"])
    assert connections.active_connections(ctx["x"].id)


def test_autorizacao_de_outro_sistema_nao_e_ativavel(ctx):
    grant_y = _grant(ctx, _conn(), ctx["y"])
    with pytest.raises(connections.NotFound):
        connections.activate(ctx["x"], grant_y, "vendas", "read_write", actor=ctx["owner"])


# --- Alias definido na ativação ---

def test_alias_pre_preenchido_com_o_nome_do_catalogo(ctx):
    grant = _grant(ctx, _conn("vendas-prod"), ctx["x"])
    assert _view(ctx["x"], grant)["suggested_alias"] == "vendas-prod"


@pytest.mark.parametrize(("name", "expected"), [
    ("Estoque legado", "estoque-legado"),
    ("Produção — Vendas (2026)", "producao-vendas-2026"),
    ("***", "banco"),
])
def test_alias_sugerido_ja_vem_no_formato_aceito(ctx, name, expected):
    grant = _grant(ctx, _conn(name), ctx["x"])
    suggested = _view(ctx["x"], grant)["suggested_alias"]
    assert suggested == expected
    connections.activate(ctx["x"], grant, suggested, "read_write", actor=ctx["owner"])


def test_alias_em_uso_ou_mesma_variavel_recusado(ctx):
    g1 = _grant(ctx, _conn("A"), ctx["x"])
    g2 = _grant(ctx, _conn("B"), ctx["x"])
    g3 = _grant(ctx, _conn("C"), ctx["x"])
    connections.activate(ctx["x"], g1, "vendas-db", "read_write", actor=ctx["owner"])
    with pytest.raises(connections.AliasTaken):
        connections.activate(ctx["x"], g2, "vendas-db", "read_write", actor=ctx["owner"])
    with pytest.raises(connections.AliasTaken):
        connections.activate(ctx["x"], g3, "VENDAS_DB", "read_write", actor=ctx["owner"])


@pytest.mark.parametrize("alias", ["", "   ", "com espaço", "acentuação", "a/b", "x" * 121])
def test_alias_invalido_recusado(ctx, alias):
    grant = _grant(ctx, _conn(), ctx["x"])
    with pytest.raises(connections.InvalidAlias):
        connections.activate(ctx["x"], grant, alias, "read_write", actor=ctx["owner"])


def test_alias_nao_muda_com_a_conexao_ativa(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    with pytest.raises(connections.InvalidAlias):
        connections.activate(ctx["x"], grant, "outro", "read_write", actor=ctx["owner"])
    assert _view(ctx["x"], grant)["alias"] == "vendas"


def test_reativacao_pode_trocar_o_alias(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    connections.deactivate(ctx["x"], grant, actor=ctx["owner"])
    assert _view(ctx["x"], grant)["suggested_alias"] == "vendas"
    connections.activate(ctx["x"], grant, "erp", "read_write", actor=ctx["owner"])
    assert connections.active_connections(ctx["x"].id)[0].alias == "erp"


def test_alias_migrado_fora_do_formato_reativa_com_a_mesma_variavel(ctx):
    """A migração guarda o nome antigo como alias (ex.: `Estoque legado`, com espaço), que o
    formato de hoje recusa. Na reativação a sugestão já vem aceitável e gera a mesma
    `DATABASE_URL_ESTOQUE_LEGADO` que a app usava."""
    from appaiforge.models import DbConnectionGrant

    grant = _grant(ctx, _conn("Estoque legado (x)"), ctx["x"])
    with session_scope() as s:
        row = s.get(DbConnectionGrant, grant)
        row.alias, row.alias_key, row.mode, row.active = "Estoque legado", "ESTOQUE_LEGADO", "read_write", False
    suggested = _view(ctx["x"], grant)["suggested_alias"]
    assert suggested == "estoque-legado"
    connections.activate(ctx["x"], grant, suggested, "read_write", actor=ctx["owner"])
    assert connections.active_connections(ctx["x"].id)[0].env_name == "ESTOQUE_LEGADO"


def test_mesma_conexao_com_aliases_diferentes(ctx):
    conn = _conn()
    gx = _grant(ctx, conn, ctx["x"])
    gy = _grant(ctx, conn, ctx["y"])
    connections.activate(ctx["x"], gx, "vendas", "read_write", actor=ctx["owner"])
    connections.activate(ctx["y"], gy, "erp", "read_write", actor=ctx["other"])
    assert connections.active_connections(ctx["x"].id)[0].env_name == "VENDAS"
    assert connections.active_connections(ctx["y"].id)[0].env_name == "ERP"


# --- Modo de acesso ativo limitado ao teto ---

def test_ativa_abaixo_do_teto(ctx):
    grant = _grant(ctx, _conn(), ctx["x"], "read_write")
    connections.activate(ctx["x"], grant, "vendas", "read_only", actor=ctx["owner"])
    assert _view(ctx["x"], grant)["mode"] == "read_only"


def test_modo_acima_do_teto_recusado(ctx):
    grant = _grant(ctx, _conn(), ctx["x"], "read_write")
    with pytest.raises(connections.InvalidMode, match="teto"):
        connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    with pytest.raises(connections.InvalidMode, match="teto"):
        connections.set_mode(ctx["x"], grant, "schema_admin", actor=ctx["owner"])


def test_dono_rebaixa_o_modo(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    refreshes.clear()
    connections.set_mode(ctx["x"], grant, "read_write", actor=ctx["owner"])
    assert connections.active_connections(ctx["x"].id)[0].mode == "read_write"
    assert refreshes == [[ctx["x"].id]]


# --- Indicação de DDL liberada ---

def test_selo_de_ddl_nos_dois_lados_e_some_ao_rebaixar(ctx):
    conn = _conn()
    grant = _grant(ctx, conn, ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    since_owner = _view(ctx["x"], grant)["schema_admin_since"]
    since_dba = connections.list_grants(conn)[0]["schema_admin_since"]
    assert since_owner and since_owner == since_dba
    connections.set_mode(ctx["x"], grant, "read_write", actor=ctx["owner"])
    assert _view(ctx["x"], grant)["schema_admin_since"] is None
    assert connections.list_grants(conn)[0]["schema_admin_since"] is None


def test_selo_some_ao_desativar(ctx):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    connections.deactivate(ctx["x"], grant, actor=ctx["owner"])
    assert _view(ctx["x"], grant)["schema_admin_since"] is None


# --- Confirmação ao conceder schema_admin em conexão compartilhada ---

def test_schema_admin_em_conexao_compartilhada_pede_confirmacao(ctx):
    conn = _conn()
    _grant(ctx, conn, ctx["y"])
    _grant(ctx, conn, ctx["z"])
    with pytest.raises(connections.NeedsConfirmation) as exc:
        _grant(ctx, conn, ctx["x"], "schema_admin")
    assert [s["slug"] for s in exc.value.systems] == ["acc-y", "acc-z"]
    grant = _grant(ctx, conn, ctx["x"], "schema_admin", confirmed=True)
    assert _view(ctx["x"], grant)["max_mode"] == "schema_admin"


def test_elevar_teto_em_conexao_compartilhada_pede_confirmacao(ctx):
    conn = _conn()
    _grant(ctx, conn, ctx["y"])
    grant = _grant(ctx, conn, ctx["x"])
    with pytest.raises(connections.NeedsConfirmation):
        connections.set_ceiling(grant, "schema_admin", actor=ctx["dba"])
    connections.set_ceiling(grant, "schema_admin", actor=ctx["dba"], confirmed=True)


def test_schema_admin_em_conexao_de_um_sistema_nao_pede_confirmacao(ctx):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    assert _view(ctx["x"], grant)["max_mode"] == "schema_admin"


# --- Revogação imediata ---

def test_revogacao_de_conexao_ativa(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    refreshes.clear()
    assert connections.revoke_grant(grant, actor=ctx["dba"]) == {"rotate_key": False}
    assert connections.active_connections(ctx["x"].id) == []
    assert connections.list_system_connections(ctx["x"].id) == []
    assert refreshes == [[ctx["x"].id]]


def test_revogacao_nao_afeta_outros_sistemas(ctx, refreshes):
    conn = _conn()
    gx = _grant(ctx, conn, ctx["x"])
    gy = _grant(ctx, conn, ctx["y"])
    connections.activate(ctx["x"], gx, "vendas", "read_write", actor=ctx["owner"])
    connections.activate(ctx["y"], gy, "vendas", "read_write", actor=ctx["other"])
    refreshes.clear()
    connections.revoke_grant(gx, actor=ctx["dba"])
    assert connections.active_connections(ctx["y"].id)
    assert refreshes == [[ctx["x"].id]]


def test_revogacao_de_conexao_inativa(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"])
    refreshes.clear()
    connections.revoke_grant(grant, actor=ctx["dba"])
    assert connections.list_system_connections(ctx["x"].id) == []
    assert refreshes == []
    assert connections.list_notices(ctx["x"].id) == []


def test_dono_nao_revoga(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    with pytest.raises(PermissionError):
        connections.revoke_grant(grant, actor=ctx["owner"])


# --- Aviso de rotação de chave ao revogar BigQuery ---

def test_revogar_bigquery_ativo_pede_rotacao(ctx):
    grant = _grant(ctx, _conn("BQ", "bigquery"), ctx["x"])
    connections.activate(ctx["x"], grant, "bq", "read_only", actor=ctx["owner"])
    assert connections.revoke_grant(grant, actor=ctx["dba"]) == {"rotate_key": True}


def test_revogar_bigquery_nunca_ativado_sem_aviso(ctx):
    grant = _grant(ctx, _conn("BQ", "bigquery"), ctx["x"])
    assert connections.revoke_grant(grant, actor=ctx["dba"]) == {"rotate_key": False}


def test_excluir_bigquery_ativo_pede_rotacao(ctx):
    conn = _conn("BQ", "bigquery")
    grant = _grant(ctx, conn, ctx["x"])
    connections.activate(ctx["x"], grant, "bq", "read_only", actor=ctx["owner"])
    assert connections.delete_connection(conn, actor=ctx["dba"], confirmed=True)["rotate_key"] is True


# --- Rebaixamento de teto com efeito imediato ---

def test_teto_rebaixado_derruba_o_modo(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    refreshes.clear()
    assert connections.set_ceiling(grant, "read_write", actor=ctx["dba"]) == {"mode_lowered": True}
    assert connections.active_connections(ctx["x"].id)[0].mode == "read_write"
    assert _view(ctx["x"], grant)["schema_admin_since"] is None
    assert refreshes == [[ctx["x"].id]]


def test_teto_rebaixado_sem_atingir_o_modo(ctx, refreshes):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "read_only", actor=ctx["owner"])
    refreshes.clear()
    assert connections.set_ceiling(grant, "read_write", actor=ctx["dba"]) == {"mode_lowered": False}
    assert _view(ctx["x"], grant)["mode"] == "read_only"
    assert refreshes == []


# --- Aviso ao dono sobre revogação e rebaixamento ---

def test_aviso_de_revogacao(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    connections.revoke_grant(grant, actor=ctx["dba"])
    [notice] = connections.list_notices(ctx["x"].id)
    assert notice["kind"] == "revoked" and notice["alias"] == "vendas"
    assert notice["actor_email"] == "dba@acc.local" and notice["created_at"]


def test_aviso_de_rebaixamento(ctx):
    grant = _grant(ctx, _conn(), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "schema_admin", actor=ctx["owner"])
    connections.set_ceiling(grant, "read_write", actor=ctx["dba"])
    [notice] = connections.list_notices(ctx["x"].id)
    assert notice["kind"] == "ceiling_lowered" and "Leitura e escrita" in notice["detail"]


def test_dono_dispensa_o_aviso(ctx):
    grant = _grant(ctx, _conn(), ctx["x"])
    connections.activate(ctx["x"], grant, "vendas", "read_write", actor=ctx["owner"])
    connections.revoke_grant(grant, actor=ctx["dba"])
    [notice] = connections.list_notices(ctx["x"].id)
    with pytest.raises(PermissionError):
        connections.dismiss_notice(ctx["x"], notice["id"], actor=ctx["other"])
    connections.dismiss_notice(ctx["x"], notice["id"], actor=ctx["owner"])
    assert connections.list_notices(ctx["x"].id) == []


def test_mudanca_sem_efeito_nao_gera_aviso(ctx):
    g1 = _grant(ctx, _conn("A"), ctx["x"])
    connections.revoke_grant(g1, actor=ctx["dba"])
    g2 = _grant(ctx, _conn("B"), ctx["x"], "schema_admin")
    connections.activate(ctx["x"], g2, "b", "read_only", actor=ctx["owner"])
    connections.set_ceiling(g2, "read_write", actor=ctx["dba"])
    assert connections.list_notices(ctx["x"].id) == []


# --- Auditoria (task 4.6) ---

def test_auditoria_de_autorizacao_e_ativacao(ctx):
    conn = _conn()
    grant = _grant(ctx, conn, ctx["x"], "schema_admin")
    connections.activate(ctx["x"], grant, "vendas", "read_only", actor=ctx["owner"])
    connections.set_mode(ctx["x"], grant, "schema_admin", actor=ctx["owner"])
    connections.set_ceiling(grant, "read_write", actor=ctx["dba"])
    connections.deactivate(ctx["x"], grant, actor=ctx["owner"])
    connections.revoke_grant(grant, actor=ctx["dba"])
    entries = audit.list_by_system(ctx["x"].id)
    by_action = {e["action"]: e for e in entries}
    assert by_action["conn.grant"]["actor_email"] == "dba@acc.local"
    assert by_action["conn.grant"]["details"]["max_mode"] == "schema_admin"
    assert by_action["conn.activate"]["actor_email"] == "dono@acc.local"
    assert by_action["conn.activate"]["details"] == {"alias": "vendas", "mode": "read_only"}
    assert by_action["conn.mode"]["details"]["new"] == "schema_admin"
    assert by_action["conn.ceiling"]["actor_email"] == "dba@acc.local"
    assert {"conn.deactivate", "conn.revoke"} <= set(by_action)
