"""Unitários do relay HTTP(S) de saída — sem Docker.

CONNECT/relay real contra um servidor TCP de eco em loopback (mesmo padrão
do spike validado em design.md); recusa testada sem abrir conexão nenhuma
(StreamReader/Writer em memória, como os testes do dbproxy)."""

import asyncio

import pytest

from proxy import AllowList, ProtocolError, _parse_absolute_target, _parse_connect_target, handle_client


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _MemoryWriter:
    def __init__(self):
        self.buf = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def can_write_eof(self) -> bool:
        return False

    def write_eof(self) -> None:
        self.closed = True


def _reader_with(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


# ---------- parsing ----------

def test_parse_connect_target():
    assert _parse_connect_target("api.example.com:443") == ("api.example.com", 443)


def test_parse_connect_target_malformado_levanta():
    with pytest.raises(ProtocolError):
        _parse_connect_target("sem-porta")


def test_parse_absolute_target():
    host, port, path = _parse_absolute_target("http://pypi.org/simple/requests/")
    assert (host, port, path) == ("pypi.org", 80, "/simple/requests/")


def test_parse_absolute_target_https_scheme_recusado():
    with pytest.raises(ProtocolError):
        _parse_absolute_target("https://pypi.org/simple/")


# ---------- allow-list ----------

def test_allow_list_permite_so_o_que_esta_na_lista():
    allow = AllowList.from_pairs([("openrouter.ai", 443)])
    assert allow.permits("openrouter.ai", 443)
    assert not allow.permits("example.com", 443)


def test_allow_list_empty_nao_permite_nada():
    assert not AllowList.empty().permits("openrouter.ai", 443)


def test_allow_list_case_insensitive_no_host():
    allow = AllowList.from_pairs([("openrouter.ai", 443)])
    assert allow.permits("OpenRouter.AI", 443)


# ---------- CONNECT: recusa (sem abrir conexão nenhuma) ----------

def test_connect_fora_da_allow_list_e_recusado_sem_conectar():
    client_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        await handle_client(reader, client_writer, AllowList.empty(), log=lambda *a: None)

    _run(go())
    assert bytes(client_writer.buf) == b"HTTP/1.1 403 Forbidden\r\n\r\n"
    assert client_writer.closed


def test_connect_malformado_recebe_400():
    client_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(b"CONNECT sem-porta HTTP/1.1\r\n\r\n")
        await handle_client(reader, client_writer, AllowList.empty(), log=lambda *a: None)

    _run(go())
    assert bytes(client_writer.buf) == b"HTTP/1.1 400 Bad Request\r\n\r\n"


def test_metodo_desconhecido_sem_forma_http_absoluta_recebe_400():
    client_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(b"GET /so-path-relativo HTTP/1.1\r\nHost: example.com\r\n\r\n")
        await handle_client(reader, client_writer, AllowList.empty(), log=lambda *a: None)

    _run(go())
    assert bytes(client_writer.buf) == b"HTTP/1.1 400 Bad Request\r\n\r\n"


# ---------- CONNECT/HTTP: relay real contra um servidor de eco em loopback ----------

async def _start_echo_server() -> tuple[asyncio.AbstractServer, int]:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(4096)
        writer.write(b"ECO:" + data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def test_connect_permitido_faz_relay_cego_ate_o_destino():
    client_writer = _MemoryWriter()

    async def go():
        server, port = await _start_echo_server()
        async with server:
            allow = AllowList.from_pairs([("127.0.0.1", port)])
            reader = _reader_with(
                f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode()
                + b"ping"
            )
            await handle_client(reader, client_writer, allow, log=lambda *a: None)

    _run(go())
    buf = bytes(client_writer.buf)
    assert buf.startswith(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    assert buf.endswith(b"ECO:ping")


def test_requisicao_http_absoluta_permitida_e_repassada():
    client_writer = _MemoryWriter()

    async def go():
        server, port = await _start_echo_server()
        async with server:
            allow = AllowList.from_pairs([("127.0.0.1", port)])
            reader = _reader_with(
                f"GET http://127.0.0.1:{port}/path HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode()
            )
            await handle_client(reader, client_writer, allow, log=lambda *a: None)

    _run(go())
    # o servidor de eco devolve a requisição que o proxy montou, prefixada de "ECO:"
    assert b"ECO:GET /path HTTP/1.1" in bytes(client_writer.buf)


def test_requisicao_http_absoluta_repassa_headers_e_corpo():
    """Achado real (design.md): o relay descartava headers (exceto Host) e
    nunca repassava o corpo. Um servidor de eco devolve exatamente o que
    chegou, então o corpo e o header customizado têm que aparecer intactos
    do outro lado."""
    client_writer = _MemoryWriter()

    async def go():
        server, port = await _start_echo_server()
        async with server:
            allow = AllowList.from_pairs([("127.0.0.1", port)])
            body = b'{"hello":"world"}'
            reader = _reader_with(
                f"POST http://127.0.0.1:{port}/v1/messages HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"x-api-key: sk-test-123\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n".encode() + body
            )
            await handle_client(reader, client_writer, allow, log=lambda *a: None)

    _run(go())
    buf = bytes(client_writer.buf)
    assert b"x-api-key: sk-test-123" in buf
    assert b"Content-Type: application/json" in buf
    assert buf.endswith(b'{"hello":"world"}')


def test_requisicao_http_absoluta_repassa_corpo_chunked():
    client_writer = _MemoryWriter()
    chunked_body = b"5\r\nhello\r\n0\r\n\r\n"

    async def go():
        server, port = await _start_echo_server()
        async with server:
            allow = AllowList.from_pairs([("127.0.0.1", port)])
            reader = _reader_with(
                f"POST http://127.0.0.1:{port}/path HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Transfer-Encoding: chunked\r\n"
                f"\r\n".encode() + chunked_body
            )
            await handle_client(reader, client_writer, allow, log=lambda *a: None)

    _run(go())
    buf = bytes(client_writer.buf)
    assert buf.endswith(chunked_body)


def test_requisicao_http_absoluta_nao_repassa_headers_hop_by_hop():
    client_writer = _MemoryWriter()

    async def go():
        server, port = await _start_echo_server()
        async with server:
            allow = AllowList.from_pairs([("127.0.0.1", port)])
            reader = _reader_with(
                f"GET http://127.0.0.1:{port}/path HTTP/1.1\r\n"
                f"Host: evil.example.com\r\n"
                f"Proxy-Authorization: Basic xxx\r\n"
                f"Connection: keep-alive\r\n"
                f"\r\n".encode()
            )
            await handle_client(reader, client_writer, allow, log=lambda *a: None)

    _run(go())
    buf = bytes(client_writer.buf)
    assert b"Proxy-Authorization" not in buf
    assert b"evil.example.com" not in buf
    assert buf.count(b"Host:") == 1
    assert buf.count(b"Connection:") == 1
    assert b"Connection: close" in buf


def test_requisicao_http_absoluta_fora_da_allow_list_e_recusada():
    client_writer = _MemoryWriter()

    async def go():
        reader = _reader_with(b"GET http://example.com/path HTTP/1.1\r\nHost: example.com\r\n\r\n")
        await handle_client(reader, client_writer, AllowList.empty(), log=lambda *a: None)

    _run(go())
    assert bytes(client_writer.buf) == b"HTTP/1.1 403 Forbidden\r\n\r\n"
