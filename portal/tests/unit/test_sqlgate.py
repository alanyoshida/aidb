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
