"""Camada de acesso a dados obrigatória das apps geradas (spec destructive-gate).

Toda statement passa pelo classificador canônico (sqlgate) antes de tocar o banco:
- bloqueada  -> GateBlocked (nunca é enviada ao banco);
- confirmável-> GateConfirmationRequired com a SQL e a contagem estimada de linhas —
                a UI mostra o diálogo e, confirmado, chama `execute_confirmed`;
- normal     -> executa direto.

Uso na app gerada:

    pool = await asyncpg.create_pool(DATABASE_URL)
    db = DBGate(pool, connection_name="vendas")
    await db.execute("DELETE FROM clientes WHERE id = $1", 3)            # normal
    await db.execute("DELETE FROM clientes")                             # levanta GateConfirmationRequired
    await db.execute_confirmed("DELETE FROM clientes")                   # após o diálogo
"""

import asyncpg

from . import sqlgate


class GateBlocked(Exception):
    """Statement bloqueada pelo gate (DDL ou não interpretada)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class GateConfirmationRequired(Exception):
    """Statement confirmável — aguarda confirmação explícita na UI."""

    def __init__(self, sql: str, reason: str, estimated_rows: int | None):
        self.sql = sql
        self.reason = reason
        self.estimated_rows = estimated_rows
        super().__init__(f"{reason} ({estimated_rows if estimated_rows is not None else '?'} linhas)")


class DBGate:
    def __init__(self, pool: "asyncpg.Pool", connection_name: str = "", on_decision=None):
        self.pool = pool
        self.connection_name = connection_name
        self.on_decision = on_decision  # callback opcional de auditoria (sql, classe, decisão)

    def _audit(self, sql: str, classification: str, decision: str) -> None:
        if self.on_decision:
            self.on_decision(sql, classification, decision)

    def _gate(self, sql: str):
        result = sqlgate.classify(sql)
        if isinstance(result, sqlgate.Blocked):
            self._audit(sql, "bloqueada", "bloqueada")
            raise GateBlocked(result.reason)
        if isinstance(result, sqlgate.Confirmable):
            self._audit(sql, "confirmavel", "pendente")
            raise GateConfirmationRequired(sql, result.reason, None)
        self._audit(sql, "normal", "aprovada")

    async def _estimate(self, sql: str) -> int | None:
        try:
            parsed = sqlglot_parse_one(sql, dialect="postgres")
            count_sql = sqlgate.estimate_rows_sql(parsed)
            if count_sql:
                return int(await self.pool.fetchval(count_sql))
        except Exception:
            return None
        return None

    async def execute(self, sql: str, *args) -> str:
        """Executa uma statement; confirmáveis levantam GateConfirmationRequired
        com a contagem estimada de linhas (buscada no próprio banco)."""
        result = sqlgate.classify(sql)
        if isinstance(result, sqlgate.Blocked):
            self._audit(sql, "bloqueada", "bloqueada")
            raise GateBlocked(result.reason)
        if isinstance(result, sqlgate.Confirmable):
            estimated = await self._estimate(sql)
            self._audit(sql, "confirmavel", "pendente")
            raise GateConfirmationRequired(sql, result.reason, estimated)
        self._audit(sql, "normal", "aprovada")
        return await self.pool.execute(sql, *args)

    async def execute_confirmed(self, sql: str, *args) -> str:
        """Executa uma statement confirmável após o diálogo (ainda audita a decisão)."""
        result = sqlgate.classify(sql)
        if isinstance(result, sqlgate.Blocked):
            self._audit(sql, "bloqueada", "bloqueada")
            raise GateBlocked(result.reason)  # confirmação nunca destrava DDL
        if isinstance(result, sqlgate.Confirmable):
            self._audit(sql, "confirmavel", "aprovada")
        return await self.pool.execute(sql, *args)

    async def fetch(self, sql: str, *args):
        """Consultas não passam pelo gate (somente leitura)."""
        return await self.pool.fetch(sql, *args)


def sqlglot_parse_one(sql: str, dialect: str = "postgres"):
    import sqlglot

    return sqlglot.parse_one(sql, dialect=dialect)
