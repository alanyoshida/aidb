"""Classificador canônico de statements SQL do gate (ADR 0017; spec destructive-gate).

Única fonte de verdade da classificação — usada pelo portal (gate do agente) e
pela app gerada (camada dbgate). Três classes:

- Normal:      DML escopado a linhas (ex.: DELETE por chave de igualdade) — sem atrito.
- Confirmable: DELETE/UPDATE sem WHERE restritivo (tabela inteira ou conjunto amplo).
- Blocked:     DDL (DROP/TRUNCATE/ALTER/CREATE/GRANT/REVOKE/...) e statements que o
               parser não consegue interpretar (postura segura).

Regras de restrição de WHERE: apenas conjunções (AND) de igualdades
`coluna = valor/parâmetro` contendo pelo menos uma coluna contam como escopo de
linha; OR, IN, desigualdades, subqueries e tautologias (1=1, TRUE) degradam para
confirmável. Múltiplas statements numa mesma string assumem a pior classe.
"""

import dataclasses
import re

import sqlglot
from sqlglot import exp

DDL_KEYS = {
    "drop",
    "truncate",
    "truncatetable",
    "alter",
    "create",
    "grant",
    "revoke",
    "comment",
    "rename",
    "attach",
    "detach",
}

# `UNLISTEN *` é o único padrão conhecido que derruba o tokenizer do
# sqlglot inteiro (ele não reconhece `UNLISTEN` e tenta ler o `*` como
# multiplicação) — é exatamente o que o asyncpg manda sozinho ao devolver
# uma conexão pro pool (`Connection.get_reset_query()`:
# `SELECT pg_advisory_unlock_all(); CLOSE ALL; UNLISTEN *; RESET ALL;`).
# Casamento estrito por padrão (não por palavra-chave solta) — qualquer
# outra coisa que o parser não entenda continua bloqueada, postura padrão.
_UNLISTEN_STAR_RE = re.compile(r"^unlisten\s+\*$", re.IGNORECASE)


@dataclasses.dataclass
class Normal:
    """DML escopado a linhas — executa sem atrito."""


@dataclasses.dataclass
class Confirmable:
    """Afeta conjunto amplo — exige confirmação explícita."""

    reason: str


@dataclasses.dataclass
class Blocked:
    """Sempre recusada pelo gate."""

    reason: str


_RANK = {Normal: 0, Confirmable: 1, Blocked: 2}


def _worst(results) -> object:
    worst: tuple[int, object] = (0, Normal())
    for result in results:
        rank = _RANK[type(result)]
        if rank > worst[0]:
            worst = (rank, result)
    return worst[1]


def classify(sql: str):
    """Classifica o texto (uma ou mais statements) — nunca levanta exceção."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        return _classify_unparseable_batch(sql, exc)

    if not statements:
        return Blocked("statement vazia")

    return _worst(_classify_one(s) for s in statements)


def _classify_unparseable_batch(sql: str, original_exc: Exception) -> object:
    """O sqlglot falhou pra string inteira — tenta nos pedaços separados
    por `;` antes de desistir, porque um único trecho que ele não entende
    (ex.: `UNLISTEN *`) derruba o tokenizer pra string inteira mesmo com
    trechos ao lado (`CLOSE ALL`, `RESET ALL`) perfeitamente válidos
    sozinhos. Qualquer pedaço que também falhe sozinho e não bata o padrão
    estrito conhecido preserva a postura padrão: bloqueada."""
    chunks = [c.strip() for c in sql.split(";") if c.strip()]
    if not chunks:
        return Blocked("statement vazia")
    return _worst(_classify_chunk(chunk, original_exc) for chunk in chunks)


def _classify_chunk(chunk: str, original_exc: Exception) -> object:
    try:
        sub_statements = [s for s in sqlglot.parse(chunk, dialect="postgres") if s is not None]
    except sqlglot.errors.SqlglotError:
        if _UNLISTEN_STAR_RE.match(chunk):
            return Normal()
        return Blocked(f"statement não interpretada pelo parser: {original_exc}")
    if not sub_statements:
        return Blocked("statement vazia")
    return _worst(_classify_one(s) for s in sub_statements)


def _classify_one(statement: exp.Expression):
    key = statement.key.lower()
    if key in DDL_KEYS:
        return Blocked(f"DDL ({key.upper()}) é sempre bloqueada pelo gate")

    if isinstance(statement, (exp.Delete, exp.Update)):
        where = statement.args.get("where")
        if where is None:
            return Confirmable(f"{key.upper()} sem WHERE afeta a tabela inteira")
        if not _restrictive(where):
            return Confirmable("WHERE não restringe a operação a linhas específicas")
        return Normal()

    return Normal()


def _restrictive(where: exp.Where) -> bool:
    return _is_conjunctive_equality(where.this)


def _is_conjunctive_equality(node: exp.Expression) -> bool:
    node = node.unnest()
    if isinstance(node, exp.And):
        return _is_conjunctive_equality(node.this) and _is_conjunctive_equality(node.expression)
    if isinstance(node, exp.EQ):
        left, right = node.this, node.expression
        bounds = (exp.Literal, exp.Placeholder, exp.Parameter)
        for candidate, bound in ((left, right), (right, left)):
            if isinstance(candidate, exp.Column) and isinstance(bound, bounds) and _is_key_column(candidate):
                return True
        return False
    return False


def _is_key_column(column: exp.Column) -> bool:
    """Igualdade só é escopo de linha em coluna-chave (id, *_id)."""
    name = column.name.lower()
    return name == "id" or name.endswith("_id")


def is_read_only(sql: str) -> tuple[bool, str]:
    """True se TODAS as statements são leitura pura (SELECT/EXPLAIN).
    Usado pelo MCP server de leitura — escritas via MCP são sempre recusadas."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        return False, f"statement não interpretada: {exc}"
    if not statements:
        return False, "statement vazia"
    for statement in statements:
        if not isinstance(statement, (exp.Select, exp.Union)):
            return False, f"apenas leitura é permitida (recebido: {statement.key.upper()})"
    return True, ""


def estimate_rows_sql(statement: exp.Expression) -> str | None:
    """SELECT count(*) equivalente para uma DELETE/UPDATE confirmável (dbgate)."""
    where = statement.args.get("where")
    table = statement.this
    if not isinstance(table, exp.Table):
        return None
    count = exp.select("count(*)").from_(table.copy())
    if where is not None:
        count = count.where(where.this.copy())
    return count.sql(dialect="postgres")
