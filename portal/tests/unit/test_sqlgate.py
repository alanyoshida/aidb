"""Unitários do classificador canônico (spec destructive-gate, task 1.1)."""

import pytest

from appaiforge.app_template import sqlgate
from appaiforge.app_template.sqlgate import Blocked, Confirmable, Normal


def _cls(sql: str):
    return type(sqlgate.classify(sql))


def test_delete_por_pk_e_normal():
    assert _cls("DELETE FROM clientes WHERE id = 3") is Normal
    assert isinstance(sqlgate.classify("DELETE FROM clientes WHERE id = 3"), Normal)


def test_delete_sem_where_e_confirmavel():
    result = sqlgate.classify("DELETE FROM clientes")
    assert isinstance(result, Confirmable)
    assert "WHERE" in result.reason


def test_delete_por_cidade_e_confirmavel():
    assert isinstance(sqlgate.classify("DELETE FROM clientes WHERE cidade = 'São Paulo'"), Confirmable)


def test_update_sem_where_e_confirmavel():
    assert _cls("UPDATE clientes SET ativo = false") is Confirmable


def test_update_por_pk_e_normal():
    assert _cls("UPDATE clientes SET ativo = false WHERE id = 3") is Normal


@pytest.mark.parametrize("sql", [
    "UPDATE clientes SET ativo = false WHERE 1 = 1",
    "UPDATE clientes SET ativo = false WHERE id = 1 OR 1 = 1",
    "DELETE FROM clientes WHERE TRUE",
    "DELETE FROM clientes WHERE id IN (1, 2, 3)",
    "DELETE FROM clientes WHERE criado_em < now()",
    "DELETE FROM clientes WHERE id = (SELECT id FROM clientes LIMIT 1)",
])
def test_where_nao_escopado_degrada_para_confirmavel(sql):
    assert _cls(sql) is Confirmable


def test_conjuncao_de_igualdades_e_normal():
    assert _cls("DELETE FROM clientes WHERE id = 3 AND tenant_id = 7") is Normal


@pytest.mark.parametrize("sql", [
    "DROP TABLE clientes",
    "truncate table clientes",
    "ALTER TABLE clientes DROP COLUMN email",
    "CREATE TABLE x (id int)",
    "GRANT ALL ON clientes TO public",
])
def test_ddl_e_bloqueado(sql):
    assert _cls(sql) is Blocked


def test_drop_escondido_em_cte_e_comentario_e_bloqueado():
    result = sqlgate.classify("WITH x AS (SELECT 1) /* limpeza */ DROP TABLE clientes")
    assert isinstance(result, Blocked)
    assert "DROP" in result.reason


def test_multiplas_statements_assumem_pior_classe():
    assert _cls("SELECT 1; DROP TABLE clientes") is Blocked
    assert _cls("DELETE FROM clientes; DELETE FROM other WHERE id = 1") is Confirmable
    assert _cls("SELECT 1; DELETE FROM t WHERE id = 1") is Normal


def test_select_e_insert_sao_normais():
    assert _cls("SELECT * FROM clientes") is Normal
    assert _cls("INSERT INTO clientes (nome) VALUES ('Ana')") is Normal


def test_parser_nao_interpreta_e_bloqueado():
    result = sqlgate.classify(";;; selet * fro clientes ~~")
    assert isinstance(result, Blocked)


def test_estimate_rows_sql_para_confirmavel():
    result = sqlgate.classify("DELETE FROM clientes WHERE cidade = 'São Paulo'")
    assert isinstance(result, Confirmable)
    sql = sqlgate.estimate_rows_sql(
        __import__("sqlglot").parse_one("DELETE FROM clientes WHERE cidade = 'São Paulo'", dialect="postgres")
    )
    assert sql.upper().startswith("SELECT COUNT(*)")
    assert "clientes" in sql.lower()
    assert "cidade" in sql.lower()


def test_copia_do_gated_mcp_identica_ao_classificador_canonico():
    from pathlib import Path

    canonico = Path(sqlgate.__file__)
    copia_mcp = Path(__file__).resolve().parents[3] / "base-image" / "gated-mcp" / "sqlgate.py"
    assert copia_mcp.read_bytes() == canonico.read_bytes(), (
        "base-image/gated-mcp/sqlgate.py divergiu de app_template/sqlgate.py; "
        "copie o original para o gated-mcp"
    )


def test_copia_do_dbproxy_identica_ao_classificador_canonico():
    from pathlib import Path

    canonico = Path(sqlgate.__file__)
    copia_dbproxy = Path(__file__).resolve().parents[3] / "base-image" / "dbproxy" / "sqlgate.py"
    assert copia_dbproxy.read_bytes() == canonico.read_bytes(), (
        "base-image/dbproxy/sqlgate.py divergiu de app_template/sqlgate.py; "
        "copie o original para o dbproxy"
    )


def test_statement_que_so_falha_no_tokenizer_e_bloqueada_sem_levantar():
    """Regressão: `select $$` (probe interno do cliente `mysql` oficial,
    mandado antes de qualquer statement do usuário) quebra o tokenizer do
    sqlglot com TokenError (não ParseError) sob o dialeto postgres —
    descoberto pelo proxy MySQL (task 3.1) contra um cliente `mysql` real.
    O classificador promete nunca levantar exceção; sem capturar
    `SqlglotError` (base de ParseError e TokenError), essa promessa quebra."""
    result = sqlgate.classify("select $$")
    assert isinstance(result, Blocked)


def test_reset_query_do_asyncpg_e_normal():
    """Achado real (change agent-https-forward-proxy, testado ao vivo):
    `UNLISTEN *` sozinho derruba o tokenizer do sqlglot inteiro (não
    reconhece `UNLISTEN`, tenta ler o `*` como multiplicação) — e é
    exatamente o reset que o próprio asyncpg manda ao devolver uma conexão
    pro pool (`Connection.get_reset_query()`). Sem tratamento, toda app
    gerada usando `asyncpg.create_pool()` (padrão comum) ficava bloqueada
    pelo gate a cada devolução de conexão — nenhum dos comandos do reset
    toca dado de tabela."""
    result = sqlgate.classify(
        "SELECT pg_advisory_unlock_all(); CLOSE ALL; UNLISTEN *; RESET ALL;"
    )
    assert isinstance(result, Normal)


def test_unlisten_star_escondendo_delete_nao_vira_normal():
    """O fallback por pedaço (`;`) não deve deixar passar algo perigoso só
    porque está ao lado de um `UNLISTEN *` válido — cada pedaço continua
    classificado por conta própria."""
    result = sqlgate.classify("UNLISTEN *; DELETE FROM clientes;")
    assert isinstance(result, Confirmable)
