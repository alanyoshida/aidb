"""Migração para o catálogo de conexões (change add-db-manager-role, tasks 1.3 e 1.4).

Roda o Alembic de verdade: sobe o schema até a revisão anterior, grava conexões no modelo
antigo (por sistema) e confere a conversão para catálogo + autorizações, e a volta.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from appaiforge.db import get_engine, reset_engine

BEFORE = "a0b1c2d3e4f5"
CATALOG = "b6c7d8e9f0a1"
PORTAL = Path(__file__).resolve().parents[2]


@pytest.fixture()
def alembic_cfg(database_url):
    reset_engine()
    with get_engine().begin() as cx:
        cx.execute(text("DROP SCHEMA public CASCADE"))
        cx.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(PORTAL / "alembic.ini"))
    cfg.set_main_option("script_location", str(PORTAL / "migrations"))
    yield cfg
    reset_engine()
    with get_engine().begin() as cx:
        cx.execute(text("DROP SCHEMA public CASCADE"))
        cx.execute(text("CREATE SCHEMA public"))


def _seed_old_schema(cfg) -> None:
    command.upgrade(cfg, BEFORE)
    with get_engine().begin() as cx:
        cx.execute(text(
            "INSERT INTO users (id, email, type, active, theme, created_at, break_glass) VALUES "
            "('u1', 'ed@m.local', 'editor', true, 'light-indigo', now(), false)"
        ))
        for sid, slug in (("s1", "sys-a"), ("s2", "sys-b")):
            cx.execute(text(
                "INSERT INTO systems (id, slug, name, owner_id, provider, model, status, status_message, "
                "execution_mode, identity_secret, kind, agent_profile, inference_token_version, "
                "internet_enabled, restricted_network, created_at, updated_at) VALUES "
                f"('{sid}', '{slug}', '{slug}', 'u1', 'glm', 'glm-4.6', 'active', '', 'reduced', 'x', "
                "'agent', 'opencode', 0, true, false, now(), now())"
            ))
        conns = [
            ("c1", "s1", "main", "read_only"),
            ("c2", "s2", "main", "read_write"),
            ("c3", "s2", "a-b", "read_write"),
            ("c4", "s2", "a_b", "read_write"),
        ]
        for i, (cid, sid, name, mode) in enumerate(conns):
            cx.execute(text(
                "INSERT INTO db_connections (id, system_id, name, kind, host, port, database, username, "
                "password_encrypted, access_mode, status, created_at) VALUES "
                f"('{cid}', '{sid}', '{name}', 'postgres', 'db', 5432, 'app', 'u', 'x', '{mode}', 'unknown', "
                f"now() + interval '{i} seconds')"
            ))


def _grants():
    with get_engine().connect() as cx:
        return {
            r.connection_id: r
            for r in cx.execute(text("SELECT * FROM db_connection_grants")).all()
        }


def test_conexoes_viram_catalogo_autorizado_e_ativo(alembic_cfg):
    _seed_old_schema(alembic_cfg)
    command.upgrade(alembic_cfg, CATALOG)

    with get_engine().connect() as cx:
        names = dict(cx.execute(text("SELECT id, name FROM db_connections")).all())
        cols = {r[0] for r in cx.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'db_connections'"
        ))}
    assert names["c1"] == "main (sys-a)"
    assert names["c2"] == "main (sys-b)"
    assert "system_id" not in cols and "access_mode" not in cols

    grants = _grants()
    assert grants["c1"].system_id == "s1" and grants["c1"].active
    assert grants["c1"].alias == "main"
    assert grants["c1"].max_mode == "read_only" and grants["c1"].mode == "read_only"
    assert grants["c2"].system_id == "s2" and grants["c2"].alias == "main"
    assert grants["c2"].max_mode == "read_write" and grants["c2"].mode == "read_write"


def test_nomes_que_geravam_a_mesma_variavel_ficam_um_ativo_e_aviso(alembic_cfg):
    _seed_old_schema(alembic_cfg)
    command.upgrade(alembic_cfg, CATALOG)
    grants = _grants()
    assert grants["c3"].active is True
    assert grants["c4"].active is False
    with get_engine().connect() as cx:
        notices = cx.execute(text("SELECT system_id, kind, alias FROM system_connection_notices")).all()
    assert [(n.system_id, n.kind, n.alias) for n in notices] == [("s2", "migration_conflict", "a_b")]


def test_ida_e_volta_com_uma_autorizacao_por_conexao(alembic_cfg):
    _seed_old_schema(alembic_cfg)
    command.upgrade(alembic_cfg, CATALOG)
    command.downgrade(alembic_cfg, BEFORE)
    with get_engine().connect() as cx:
        rows = {
            r.id: r for r in cx.execute(text("SELECT id, system_id, name, access_mode FROM db_connections")).all()
        }
        tables = {r[0] for r in cx.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ))}
    assert rows["c1"].system_id == "s1" and rows["c1"].name == "main" and rows["c1"].access_mode == "read_only"
    assert rows["c3"].name == "a-b" and rows["c4"].name == "a_b"
    assert "db_connection_grants" not in tables


def test_volta_aborta_com_conexao_compartilhada(alembic_cfg):
    _seed_old_schema(alembic_cfg)
    command.upgrade(alembic_cfg, CATALOG)
    with get_engine().begin() as cx:
        cx.execute(text(
            "INSERT INTO db_connection_grants (id, connection_id, system_id, max_mode, active, mode, created_at) "
            "VALUES ('g-extra', 'c1', 's2', 'read_write', false, 'read_write', now())"
        ))
    with pytest.raises(RuntimeError, match="main \\(sys-a\\)"):
        command.downgrade(alembic_cfg, BEFORE)
