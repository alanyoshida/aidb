"""Provisionamento pelo alias (change add-db-manager-role, task 5.1, design D6): o mesmo leitor
de conexões vigentes alimenta o manifesto do sidecar, o `DATABASE_URL_<ALIAS>`, a config do
opencode e a do Claude Code. Conexão autorizada e inativa não aparece em nenhum deles."""

import json

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import DbConnectionGrant, UserType
from appaiforge.provisioning import (
    _connection_env,
    db_connections_manifest,
    write_claude_code_config,
    write_opencode_config,
)
from appaiforge.services.systems import create_system


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("alias@prov.local", "pw", UserType.editor.value)


def _artifacts(system, tmp_path) -> dict:
    manifest = db_connections_manifest(system.id)
    env = _connection_env(system.id, manifest)
    oc_dir, cc_dir = tmp_path / "oc", tmp_path / "cc"
    write_opencode_config(system, str(oc_dir), manifest)
    write_claude_code_config(system, str(cc_dir), manifest)
    opencode = json.loads((oc_dir / "opencode.json").read_text())
    cc_path = cc_dir / "mcp-servers.json"
    claude = json.loads(cc_path.read_text())["mcpServers"] if cc_path.exists() else {}
    return {"manifest": manifest, "env": env, "opencode": opencode["mcp"], "claude": claude}


def test_mesma_conexao_com_aliases_diferentes_em_dois_sistemas(editor, tmp_path, active_connection):
    x = create_system(editor, "X", "alias-x")
    y = create_system(editor, "Y", "alias-y")
    conn_id = active_connection(x, "vendas", name="Vendas prod")
    with session_scope() as s:
        s.add(DbConnectionGrant(connection_id=conn_id, system_id=y.id, max_mode="read_write",
                                mode="read_write", active=True, alias="erp", alias_key="ERP"))
    ax, ay = _artifacts(x, tmp_path / "x"), _artifacts(y, tmp_path / "y")
    assert set(ax["env"]) == {"DATABASE_URL_VENDAS"} and set(ay["env"]) == {"DATABASE_URL_ERP"}
    assert [m["name"] for m in ax["manifest"]] == ["vendas"]
    assert [m["name"] for m in ay["manifest"]] == ["erp"]
    assert list(ax["opencode"]) == ["vendas"] and list(ay["claude"]) == ["erp"]
    dump = json.dumps([ax, ay])
    assert "Vendas prod" not in dump  # o nome do catálogo não chega ao container


def test_conexao_autorizada_e_inativa_nao_aparece(editor, tmp_path, active_connection):
    x = create_system(editor, "X", "alias-inativa")
    active_connection(x, "ligada")
    conn_off = active_connection(x, "desligada")
    with session_scope() as s:
        s.query(DbConnectionGrant).filter_by(connection_id=conn_off).update({"active": False})
    art = _artifacts(x, tmp_path)
    assert set(art["env"]) == {"DATABASE_URL_LIGADA"}
    assert [m["name"] for m in art["manifest"]] == ["ligada"]
    assert list(art["opencode"]) == ["ligada"] and list(art["claude"]) == ["ligada"]
    assert "desligada" not in json.dumps(art)


def test_manifesto_leva_o_modo_vigente(editor, active_connection):
    x = create_system(editor, "X", "alias-modo")
    active_connection(x, "ddl", mode="schema_admin")
    active_connection(x, "leitura", mode="read_only")
    modes = {m["name"]: m["mode"] for m in db_connections_manifest(x.id)}
    assert modes == {"ddl": "schema_admin", "leitura": "read_only"}


def test_sem_conexao_ativa_nao_ha_artefato(editor, tmp_path):
    x = create_system(editor, "X", "alias-vazio")
    art = _artifacts(x, tmp_path)
    assert art == {"manifest": [], "env": {}, "opencode": {}, "claude": {}}


def test_rotulo_da_ferramenta_leva_descricao_e_modo(editor, tmp_path, active_connection):
    """Spec "Contexto da conexão exposto ao agente" (task 6.4)."""
    x = create_system(editor, "X", "alias-rotulo")
    active_connection(x, "ddl", mode="schema_admin", description="Banco novo")
    active_connection(x, "leitura", mode="read_only")
    active_connection(x, "normal", mode="read_write")
    art = _artifacts(x, tmp_path)
    assert set(art["opencode"]) == {"ddl [Banco novo] (DDL liberada)", "leitura (somente-leitura)", "normal"}
    modes = {label: entry["command"][-1] for label, entry in art["opencode"].items()}
    assert modes["ddl [Banco novo] (DDL liberada)"] == "schema_admin"
    assert art["claude"]["ddl"]["args"][-1] == "schema_admin"
