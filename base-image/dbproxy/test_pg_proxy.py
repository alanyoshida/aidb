"""Unitários do framing e da autenticação upstream do pg_proxy — sem Docker.

SCRAM-SHA-256 e md5 são exercitados contra um servidor Postgres **falso** (TCP
loopback, implementa só o suficiente do protocolo pro fluxo de auth) para
provar o cálculo sem depender de um Postgres real; a validação end-to-end com
`psql`/`asyncpg` contra Postgres real está registrada no design (spike S8) e
foi reconfirmada manualmente com este módulo antes de marcar a task 2.1.

Sem pytest-asyncio (base-image não gerencia deps de teste como o portal) —
mesmo padrão do test_mcp_access_mode.py: roda a corrotina com um event loop
próprio em cada teste síncrono.
"""

import asyncio
import base64
import hashlib
import hmac
import struct

import pytest

import pg_proxy
from pg_proxy import (
    GateContext,
    ProtocolError,
    UpstreamConfig,
    _md5_auth,
    _pump_client_to_upstream,
    _scram_sha256_auth,
    authentication_ok,
    encode_startup,
    error_response,
    extract_sql,
    read_message,
    read_startup_packet,
    ready_for_query,
)

_GATE_CTX = GateContext(system_id="sys-test")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _MemoryWriter:
    """Stand-in de StreamWriter: só acumula bytes escritos."""

    def __init__(self):
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        pass


def _reader_with(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


# ---------- framing ----------

def test_read_message_roundtrip():
    payload = b"SELECT 1\x00"
    raw = b"Q" + struct.pack("!i", 4 + len(payload)) + payload

    async def go():
        reader = _reader_with(raw)
        return await read_message(reader)

    msg = _run(go())
    assert msg == raw
    assert msg[0:1] == b"Q"


def test_startup_params_roundtrip():
    params = {"user": "spike", "database": "spike", "client_encoding": "UTF8"}
    writer = _MemoryWriter()

    async def go():
        reader = _reader_with(encode_startup(params))
        return await read_startup_packet(reader, writer)

    parsed = _run(go())
    assert parsed == params
    assert bytes(writer.buf) == b""  # nenhum 'N' deveria ter sido escrito


def test_sslrequest_then_startup_responde_n_e_segue():
    ssl_request = struct.pack("!i", 8) + struct.pack("!i", 80877103)
    params = {"user": "spike", "database": "spike"}
    writer = _MemoryWriter()

    async def go():
        reader = _reader_with(ssl_request + encode_startup(params))
        return await read_startup_packet(reader, writer)

    parsed = _run(go())
    assert bytes(writer.buf) == b"N"
    assert parsed == params


def test_authentication_ok_bytes():
    msg = authentication_ok()
    assert msg[0:1] == b"R"
    assert struct.unpack("!i", msg[5:9])[0] == 0


def test_ready_for_query_bytes():
    assert ready_for_query() == b"Z" + struct.pack("!i", 5) + b"I"


def test_error_response_contains_message_and_code():
    msg = error_response("ddl bloqueada pelo gate: DROP", code="42501")
    assert msg[0:1] == b"E"
    assert b"42501" in msg
    assert b"ddl bloqueada pelo gate: DROP" in msg


# ---------- autenticação upstream contra um servidor Postgres falso ----------

async def _fake_md5_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                           user: str, password: str) -> None:
    salt = b"\x01\x02\x03\x04"
    writer.write(b"R" + struct.pack("!i", 12) + struct.pack("!i", 5) + salt)
    await writer.drain()
    header = await reader.readexactly(5)
    length = struct.unpack("!i", header[1:5])[0]
    resp = await reader.readexactly(length - 4)
    expected_inner = hashlib.md5(password.encode() + user.encode()).hexdigest()
    expected = f"md5{hashlib.md5(expected_inner.encode() + salt).hexdigest()}".encode() + b"\x00"
    if resp == expected:
        writer.write(b"R" + struct.pack("!i", 8) + struct.pack("!i", 0))
    else:
        writer.write(error_response("senha incorreta", code="28P01"))
    await writer.drain()
    writer.close()


def test_md5_auth_contra_servidor_falso_senha_correta():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_md5_server(r, w, "spike", "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await reader.readexactly(9)
            salt = await reader.readexactly(4)
            await _md5_auth(reader, writer, "spike", "segredo", salt)
            ok = await read_message(reader)
            assert ok[0:1] == b"R"
            assert struct.unpack("!i", ok[5:9])[0] == 0
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())


async def _fake_scram_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, password: str) -> None:
    # o AuthenticationSASL (code 10, lista de mecanismos) é consumido por
    # connect_upstream antes de chamar _scram_sha256_auth — este fake só
    # exercita o que a função realmente faz, a partir do SASLInitialResponse.
    msg = await read_message(reader)
    body = msg[5:]
    nul = body.index(b"\x00")
    gs2_and_bare = body[nul + 1:]
    client_first_bare = gs2_and_bare[4:].decode()[3:]  # pula o length-prefix do gs2-header e o "n,,"
    client_nonce = dict(kv.split("=", 1) for kv in client_first_bare.split(","))["r"]

    salt = b"spikesalt0123456"
    iterations = 4096
    full_nonce = client_nonce + "serverpart"
    server_first_msg = f"r={full_nonce},s={base64.b64encode(salt).decode()},i={iterations}".encode()
    writer.write(b"R" + struct.pack("!i", 8 + len(server_first_msg)) + struct.pack("!i", 11) + server_first_msg)
    await writer.drain()

    msg = await read_message(reader)
    client_final = msg[5:].decode()
    proof_b64 = dict(kv.split("=", 1) for kv in client_final.split(",") if "=" in kv)["p"]
    client_final_wo_proof = client_final.rsplit(",p=", 1)[0]

    salted_password = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    auth_message = f"n=,r={client_nonce},{server_first_msg.decode()},{client_final_wo_proof}".encode()
    expected_sig = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
    received_client_key = bytes(a ^ b for a, b in zip(base64.b64decode(proof_b64), expected_sig))

    if received_client_key != client_key:
        writer.write(error_response("autenticação SCRAM falhou", code="28P01"))
        await writer.drain()
        writer.close()
        return

    server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()
    server_sig = hmac.new(server_key, auth_message, hashlib.sha256).digest()
    server_final_msg = f"v={base64.b64encode(server_sig).decode()}".encode()
    writer.write(b"R" + struct.pack("!i", 8 + len(server_final_msg)) + struct.pack("!i", 12) + server_final_msg)
    await writer.drain()
    writer.close()


def test_scram_sha256_contra_servidor_falso_senha_correta():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_scram_server(r, w, "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await _scram_sha256_auth(reader, writer, "segredo")
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())


def test_scram_sha256_senha_errada_levanta_protocol_error():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_scram_server(r, w, "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            with pytest.raises(ProtocolError):
                await _scram_sha256_auth(reader, writer, "senha-errada")
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())


def test_upstream_config_from_dsn():
    cfg = UpstreamConfig.from_dsn("postgresql://spike:segredo@127.0.0.1:55432/spike")
    assert cfg == UpstreamConfig(host="127.0.0.1", port=55432, user="spike", password="segredo", database="spike")


# ---------- extração de SQL (Q e Parse) ----------

def test_extract_sql_simple_query():
    assert extract_sql(b"Q", b"SELECT 1\x00") == "SELECT 1"


def test_extract_sql_parse_ignora_nome_e_tipos_dos_params():
    payload = b"meustmt\x00DELETE FROM t WHERE id = $1\x00" + struct.pack("!h", 0)
    assert extract_sql(b"P", payload) == "DELETE FROM t WHERE id = $1"


def test_extract_sql_outras_tags_sao_none():
    assert extract_sql(b"B", b"qualquer coisa") is None


# ---------- classificação no Q/Parse (task 2.2) — bloqueada nunca chega ao upstream ----------

def _q(sql: str) -> bytes:
    payload = sql.encode() + b"\x00"
    return b"Q" + struct.pack("!i", 4 + len(payload)) + payload


def _parse_msg(sql: str, name: str = "") -> bytes:
    payload = name.encode() + b"\x00" + sql.encode() + b"\x00" + struct.pack("!h", 0)
    return b"P" + struct.pack("!i", 4 + len(payload)) + payload


def _simple_msg(tag: bytes, payload: bytes = b"") -> bytes:
    return tag + struct.pack("!i", 4 + len(payload)) + payload


def test_bloqueada_simple_query_drop_nao_chega_ao_upstream():
    drop = _q("DROP TABLE t")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == terminate  # DROP nunca chega ao banco, só o Terminate
    expected_client = error_response("DDL (DROP) é sempre bloqueada pelo gate", code="42501", severity="ERROR") + ready_for_query()
    assert bytes(client_writer.buf) == expected_client


def test_bloqueada_em_enforce_tambem_audita_com_enforced_true(monkeypatch):
    """Fechamento de lacuna (roteiro de teste manual): uma DDL recusada em
    enforce precisa deixar rastro em GateDecision, não só reusar a conexão
    o quanto antes — por isso audit_shadow(enforced=True)."""
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append((sql, kwargs.get("enforced")))

    monkeypatch.setattr(pg_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    drop = _q("DROP TABLE t")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert audited == [("DROP TABLE t", True)]


def test_normal_delete_por_pk_e_repassada_sem_tocar_cliente():
    delete = _q("DELETE FROM t WHERE id = 1")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == delete + terminate
    assert bytes(client_writer.buf) == b""


# ---------- confirmável em enforce: recusada direto, sem pedir aprovação (decisão do operador) ----------

def test_confirmavel_em_enforce_e_recusada_direto_sem_chegar_ao_upstream():
    """Uma DELETE/UPDATE sem WHERE restritivo é tratada como destrutiva
    igual a um DDL: recusada na hora, sem segurar a conexão nem consultar
    o portal por uma decisão humana."""
    delete_sem_where = _q("DELETE FROM t")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_sem_where + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == terminate  # DELETE nunca chega ao banco
    expected_client = (
        error_response("DELETE sem WHERE afeta a tabela inteira", code="42501", severity="ERROR") + ready_for_query()
    )
    assert bytes(client_writer.buf) == expected_client


def test_confirmavel_em_enforce_tambem_audita_com_enforced_true(monkeypatch):
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append((sql, kwargs.get("enforced")))

    monkeypatch.setattr(pg_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    delete_sem_where = _q("DELETE FROM t")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_sem_where + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert audited == [("DELETE FROM t", True)]


def test_confirmavel_via_parse_descarta_bind_execute_at_sync():
    parse = _parse_msg("DELETE FROM t")
    bind = _simple_msg(b"B", b"bind data")
    execute = _simple_msg(b"E", b"\x00" + struct.pack("!i", 0))
    sync = _simple_msg(b"S")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(parse + bind + execute + sync + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == terminate  # Parse/Bind/Execute nunca chegam ao banco
    buf = bytes(client_writer.buf)
    assert buf.endswith(ready_for_query())  # só depois do Sync, igual ao bloqueio por DDL
    assert buf[0:1] == b"E"


def test_bloqueada_parse_descarta_bind_describe_execute_at_sync():
    parse = _parse_msg("DROP TABLE t")
    bind = _simple_msg(b"B", b"bind data")
    describe = _simple_msg(b"D", b"P\x00")
    execute = _simple_msg(b"E", b"\x00" + struct.pack("!i", 0))
    sync = _simple_msg(b"S")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(parse + bind + describe + execute + sync + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == terminate  # Parse/Bind/Describe/Execute nunca chegam ao banco
    # ErrorResponse logo no Parse bloqueado; ReadyForQuery só depois do Sync (protocolo estendido)
    expected_client = error_response("DDL (DROP) é sempre bloqueada pelo gate", code="42501", severity="ERROR") + ready_for_query()
    assert bytes(client_writer.buf) == expected_client


def test_parse_normal_seguido_de_bind_execute_passa_tudo_intacto():
    parse = _parse_msg("DELETE FROM t WHERE id = $1")
    bind = _simple_msg(b"B", b"bind data")
    execute = _simple_msg(b"E", b"\x00" + struct.pack("!i", 0))
    sync = _simple_msg(b"S")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(parse + bind + execute + sync + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == parse + bind + execute + sync + terminate
    assert bytes(client_writer.buf) == b""


# ---------- modo sombra (task 6.1): classifica e audita, mas deixa tudo passar ----------

def test_sombra_delete_em_massa_executa_e_e_auditada_como_confirmavel(monkeypatch):
    """Caso de aceitação da task 6.1: um DELETE sem WHERE (confirmável) não
    é segurado em modo sombra — chega ao banco igual a uma statement normal,
    só que com uma chamada de auditoria registrando a classificação."""
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append((ctx.system_id, sql))

    monkeypatch.setattr(pg_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    delete_em_massa = _q("DELETE FROM clientes")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_em_massa + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "shadow")

    _run(go())
    assert bytes(up_writer.buf) == delete_em_massa + terminate  # executa sem segurar
    assert bytes(client_writer.buf) == b""  # cliente não percebe nada
    assert audited == [("sys-test", "DELETE FROM clientes")]


def test_sombra_drop_table_executa_e_e_auditado(monkeypatch):
    """Mesmo uma DDL (sempre bloqueada em enforce) passa em sombra — só audita."""
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append(sql)

    monkeypatch.setattr(pg_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    drop = _q("DROP TABLE clientes")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "shadow")

    _run(go())
    assert bytes(up_writer.buf) == drop + terminate
    assert bytes(client_writer.buf) == b""
    assert audited == ["DROP TABLE clientes"]


def test_sombra_e_o_default_quando_gate_mode_nao_e_passado():
    """O default do parâmetro é "shadow" — bate com o default de
    `db_gate_mode` em config.py (D5: sombra por padrão)."""
    delete_em_massa = _q("DELETE FROM clientes")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_em_massa + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX)  # sem gate_mode

    _run(go())
    assert bytes(up_writer.buf) == delete_em_massa + terminate  # não travou em network real (default é sombra)


def test_sombra_normal_nao_chama_auditoria(monkeypatch):
    """Só confirmável/bloqueada são auditadas em sombra — normal é tráfego
    de rotina demais pra valer a pena (ver docstring do pump)."""
    called = []
    monkeypatch.setattr(pg_proxy.portal_gate, "audit_shadow", lambda *a, **kw: called.append(1))

    select = _q("SELECT * FROM clientes")
    terminate = _simple_msg(b"X")
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(select + terminate)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "shadow")

    _run(go())
    assert called == []
