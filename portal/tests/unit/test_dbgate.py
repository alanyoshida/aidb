"""Unitários do dbgate (task 4.1): três classes contra Postgres real (asyncpg)."""

import pytest
import pytest_asyncio

from appaiforge.app_template.dbgate import DBGate, GateBlocked, GateConfirmationRequired

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture()
async def db():
    import asyncio

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        conn = await asyncpg_connect(
            host=pg.get_container_host_ip(),
            port=int(pg.get_exposed_port(5432)),
            user=pg.username,
            password=pg.password,
            database=pg.dbname,
        )
        await conn.execute(
            "CREATE TABLE clientes (id serial PRIMARY KEY, nome text, cidade text)"
        )
        for nome in ("Ana", "Bruno", "Carla"):
            await conn.execute("INSERT INTO clientes (nome) VALUES ($1)", nome)
        pool = _FakePool(conn)
        yield DBGate(pool, connection_name="vendas")
        await conn.close()


def asyncpg_connect(**kwargs):
    import asyncpg

    return asyncpg.connect(**kwargs)


class _FakePool:
    """asyncpg.Pool mínimo sobre uma conexão única (o dbgate só usa execute/fetchval/fetch)."""

    def __init__(self, conn):
        self._conn = conn

    async def execute(self, sql, *args):
        return await self._conn.execute(sql, *args)

    async def fetchval(self, sql, *args):
        return await self._conn.fetchval(sql, *args)

    async def fetch(self, sql, *args):
        return await self._conn.fetch(sql, *args)


async def test_dml_escopado_executa_sem_atrito(db):
    await db.pool.execute("INSERT INTO clientes (id, nome) VALUES (999, 'Zeca')")
    status = await db.execute("DELETE FROM clientes WHERE id = $1", 999)
    assert "DELETE 1" in status


async def test_delete_em_massa_exige_confirmacao_com_contagem(db):
    total_antes = (await db.fetch("SELECT count(*) AS n FROM clientes"))[0]["n"]
    with pytest.raises(GateConfirmationRequired) as exc:
        await db.execute("DELETE FROM clientes")
    assert exc.value.estimated_rows == total_antes
    assert "WHERE" in exc.value.reason

    # nada foi apagado ainda
    total = (await db.fetch("SELECT count(*) AS n FROM clientes"))[0]["n"]
    assert total == total_antes

    # confirmação executa e audita
    status = await db.execute_confirmed("DELETE FROM clientes")
    assert f"DELETE {total_antes}" in status


async def test_ddl_bloqueado_mesmo_com_confirmacao(db):
    with pytest.raises(GateBlocked):
        await db.execute("DROP TABLE clientes")
    with pytest.raises(GateBlocked):  # confirmação nunca destrava DDL
        await db.execute_confirmed("DROP TABLE clientes")


async def test_leitura_nao_passa_pelo_gate(db):
    rows = await db.fetch("SELECT nome FROM clientes ORDER BY id")
    assert len(rows) == 3
