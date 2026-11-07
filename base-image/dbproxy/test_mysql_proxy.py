"""Unitários do framing, auth upstream e gate do mysql_proxy — sem Docker.

Mesmo padrão dos testes do pg_proxy: servidor MySQL falso em loopback TCP
pro auth (sem stand-in de StreamReader/Writer, já que a auth upstream lê e
escreve pacotes reais), e portal_gate mockado pro hold da confirmável.
"""

import asyncio
import hashlib
import struct

import pytest

import mysql_proxy
from mysql_proxy import (
    GateContext,
    ProtocolError,
    UpstreamConfig,
    _pump_client_to_upstream,
    caching_sha2_token,
    err_packet,
    extract_sql,
    native_token,
    ok_packet,
    read_packet,
    upstream_auth,
    write_packet,
)

_GATE_CTX = GateContext(system_id="sys-test")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _MemoryWriter:
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

def test_read_write_packet_roundtrip():
    payload = b"\x03SELECT 1"

    async def go():
        writer = _MemoryWriter()
        write_packet(writer, 0, payload)
        reader = _reader_with(bytes(writer.buf))
        return await read_packet(reader)

    seq, got = _run(go())
    assert seq == 0
    assert got == payload


def test_ok_packet_e_err_packet_tem_cabecalho_esperado():
    assert ok_packet()[0:1] == b"\x00"
    err = err_packet("recusado", errno=1142, sqlstate="42000")
    assert err[0:1] == b"\xff"
    assert struct.unpack("<H", err[1:3])[0] == 1142
    assert b"42000" in err
    assert b"recusado" in err


def test_extract_sql_com_query_e_com_stmt_prepare():
    assert extract_sql(mysql_proxy.COM_QUERY, b"\x03DELETE FROM t") == "DELETE FROM t"
    assert extract_sql(mysql_proxy.COM_STMT_PREPARE, b"\x16DROP TABLE t") == "DROP TABLE t"


def test_extract_sql_outros_comandos_sao_none():
    assert extract_sql(mysql_proxy.COM_QUIT, b"\x01") is None


def test_upstream_config_from_dsn():
    cfg = UpstreamConfig.from_dsn("mysql://spike:segredo@127.0.0.1:53306/spike")
    assert cfg == UpstreamConfig(host="127.0.0.1", port=53306, user="spike", password="segredo", database="spike")


# ---------- autenticação upstream contra um servidor MySQL falso ----------

def _handshake_v10(seed: bytes, plugin: bytes = b"mysql_native_password") -> bytes:
    caps = mysql_proxy.SERVER_CAPS
    return (
        b"\x0a" + b"8.0-fake\x00" + struct.pack("<I", 7)
        + seed[:8] + b"\x00"
        + struct.pack("<H", caps & 0xFFFF)
        + bytes([45])
        + struct.pack("<H", 0x0002)
        + struct.pack("<H", caps >> 16)
        + bytes([21])
        + b"\x00" * 10
        + seed[8:] + b"\x00"
        + plugin + b"\x00"
    )


async def _fake_native_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                              user: str, password: str) -> None:
    seed = b"0123456789abcdefghij"
    write_packet(writer, 0, _handshake_v10(seed))
    await writer.drain()
    seq, resp = await read_packet(reader)
    expected = native_token(password, seed)
    pos = 4 + 4 + 1 + 23
    nul = resp.index(b"\x00", pos)
    token_len = resp[nul + 1]
    token = resp[nul + 2:nul + 2 + token_len]
    if token == expected:
        write_packet(writer, seq + 1, b"\x00\x00\x00\x00\x00")
    else:
        write_packet(writer, seq + 1, err_packet("acesso negado", errno=1045, sqlstate="28000"))
    await writer.drain()
    writer.close()


def test_upstream_auth_native_password_senha_correta():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_native_server(r, w, "spike", "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            cfg = UpstreamConfig(host="127.0.0.1", port=port, user="spike", password="segredo", database="spike")
            await upstream_auth(reader, writer, cfg)
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())  # não levanta -> auth OK


def test_upstream_auth_native_password_senha_errada_levanta():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_native_server(r, w, "spike", "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            cfg = UpstreamConfig(host="127.0.0.1", port=port, user="spike", password="senha-errada", database="spike")
            with pytest.raises(ProtocolError):
                await upstream_auth(reader, writer, cfg)
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())


async def _fake_authswitch_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, password: str) -> None:
    """Handshake anuncia caching_sha2 (plugin default) mas troca pra
    mysql_native_password via AuthSwitchRequest — mesmo achado do spike:
    o scramble vem com 21 bytes (20 reais + 1 de folga), truncar é
    obrigatório."""
    seed = b"0123456789abcdefghij"
    write_packet(writer, 0, _handshake_v10(seed, plugin=b"caching_sha2_password"))
    await writer.drain()
    seq, _resp = await read_packet(reader)  # resposta com o token de caching_sha2 — ignorada, troca o plugin

    switch_seed = b"zyxwvutsrqponmlkjihg"
    payload = b"\xfe" + b"mysql_native_password\x00" + switch_seed + b"\x00"  # +1 byte de folga (o bug real)
    write_packet(writer, seq + 1, payload)
    await writer.drain()

    seq2, resp2 = await read_packet(reader)
    expected = native_token(password, switch_seed)
    if resp2 == expected:
        write_packet(writer, seq2 + 1, b"\x00\x00\x00\x00\x00")
    else:
        write_packet(writer, seq2 + 1, err_packet("acesso negado", errno=1045, sqlstate="28000"))
    await writer.drain()
    writer.close()


def test_upstream_auth_authswitch_trunca_scramble_para_20_bytes():
    async def go():
        server = await asyncio.start_server(
            lambda r, w: _fake_authswitch_server(r, w, "segredo"), "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            cfg = UpstreamConfig(host="127.0.0.1", port=port, user="qualquer", password="segredo", database="spike")
            await upstream_auth(reader, writer, cfg)  # não levanta -> trucagem correta
            writer.close()
        finally:
            server.close()
            await server.wait_closed()

    _run(go())


def test_caching_sha2_token_e_deterministico():
    seed = b"0123456789abcdefghij"
    t1 = caching_sha2_token("segredo", seed)
    t2 = caching_sha2_token("segredo", seed)
    assert t1 == t2
    assert len(t1) == hashlib.sha256().digest_size


# ---------- classificação no COM_QUERY/COM_STMT_PREPARE (task 3.1) ----------

def _query_packet(seq: int, sql: str) -> bytes:
    writer = _MemoryWriter()
    write_packet(writer, seq, bytes([mysql_proxy.COM_QUERY]) + sql.encode())
    return bytes(writer.buf)


def _prepare_packet(seq: int, sql: str) -> bytes:
    writer = _MemoryWriter()
    write_packet(writer, seq, bytes([mysql_proxy.COM_STMT_PREPARE]) + sql.encode())
    return bytes(writer.buf)


def _quit_packet(seq: int) -> bytes:
    writer = _MemoryWriter()
    write_packet(writer, seq, bytes([mysql_proxy.COM_QUIT]))
    return bytes(writer.buf)


def test_bloqueada_com_query_drop_nao_chega_ao_upstream():
    drop = _query_packet(0, "DROP TABLE t")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == quit_pkt  # DROP nunca chega ao banco, só o QUIT
    assert bytes(client_writer.buf)[4:5] == b"\xff"  # ERR_Packet
    assert b"DDL (DROP)" in bytes(client_writer.buf)


def test_bloqueada_em_enforce_tambem_audita_com_enforced_true(monkeypatch):
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append((sql, kwargs.get("enforced")))

    monkeypatch.setattr(mysql_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    drop = _query_packet(0, "DROP TABLE t")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert audited == [("DROP TABLE t", True)]


def test_normal_delete_por_pk_e_repassada_sem_tocar_cliente():
    delete = _query_packet(0, "DELETE FROM t WHERE id = 1")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == delete + quit_pkt
    assert bytes(client_writer.buf) == b""


def test_bloqueada_via_com_stmt_prepare_so_err_nenhum_descarte_necessario():
    """MySQL não faz pipelining como o protocolo estendido do Postgres — um
    ERR no PREPARE já é a resposta completa, sem Bind/Execute pendurados."""
    prepare = _prepare_packet(0, "DROP TABLE t")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(prepare + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == quit_pkt
    assert bytes(client_writer.buf)[4:5] == b"\xff"


def test_confirmavel_aprovada_e_repassada(monkeypatch):
    async def fake_decide(ctx, sql, reason, **kwargs):
        return "aprovada"

    monkeypatch.setattr(mysql_proxy.portal_gate, "decide_confirmable", fake_decide)

    delete_sem_where = _query_packet(0, "DELETE FROM t")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_sem_where + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == delete_sem_where + quit_pkt
    assert bytes(client_writer.buf) == b""


def test_confirmavel_recusada_nao_chega_ao_upstream(monkeypatch):
    async def fake_decide(ctx, sql, reason, **kwargs):
        return "recusada"

    monkeypatch.setattr(mysql_proxy.portal_gate, "decide_confirmable", fake_decide)

    delete_sem_where = _query_packet(0, "DELETE FROM t")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_sem_where + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "enforce")

    _run(go())
    assert bytes(up_writer.buf) == quit_pkt
    assert b"recusada" in bytes(client_writer.buf)


# ---------- modo sombra (task 6.1) ----------

def test_sombra_delete_em_massa_executa_e_e_auditada(monkeypatch):
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append(sql)

    monkeypatch.setattr(mysql_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    delete_em_massa = _query_packet(0, "DELETE FROM clientes")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(delete_em_massa + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "shadow")

    _run(go())
    assert bytes(up_writer.buf) == delete_em_massa + quit_pkt
    assert bytes(client_writer.buf) == b""
    assert audited == ["DELETE FROM clientes"]


def test_sombra_drop_table_executa_e_e_auditado(monkeypatch):
    audited = []

    async def fake_audit_shadow(ctx, sql, **kwargs):
        audited.append(sql)

    monkeypatch.setattr(mysql_proxy.portal_gate, "audit_shadow", fake_audit_shadow)

    drop = _query_packet(0, "DROP TABLE clientes")
    quit_pkt = _quit_packet(1)
    client_writer = _MemoryWriter()
    up_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(drop + quit_pkt)
        await _pump_client_to_upstream(reader, client_writer, up_writer, _GATE_CTX, "shadow")

    _run(go())
    assert bytes(up_writer.buf) == drop + quit_pkt
    assert audited == ["DROP TABLE clientes"]
