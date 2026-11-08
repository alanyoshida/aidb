"""Proxy HTTP(S) de saída do sistema (change `agent-https-forward-proxy`).

Relay às cegas por `CONNECT host:porta` (HTTPS) ou requisição HTTP absoluta
(`GET http://host/path`, usada por ferramentas que não negociam TLS pelo
proxy) — nunca decripta nem inspeciona o conteúdo da conexão (ADR a
registrar, D3 do design). A allow-list é por `(host, porta)`, verificada
antes de abrir qualquer conexão upstream; fora dela, recusa sem tentar
alcançar o destino.

Validado por spike real (design.md) contra um host HTTPS real: handshake
TLS 1.3 completo passa intacto pelo túnel, e um destino fora da allow-list
recebe `403` sem nenhuma tentativa de conexão.
"""

from __future__ import annotations

import asyncio
import dataclasses
from urllib.parse import urlparse

_READ_CHUNK = 65536


class ProtocolError(Exception):
    """Primeira linha da requisição não é um `CONNECT` nem uma forma que o proxy entende."""


@dataclasses.dataclass(frozen=True)
class AllowList:
    """Destinos (`host`, `porta`) que este proxy libera — nunca por IP (DNS
    rebinding: resolver antes de checar abriria brecha de o host resolver
    para um IP permitido na checagem e outro na hora de conectar; aqui a
    checagem é pelo hostname que o cliente pediu, e a resolução acontece
    depois, só para abrir a conexão real)."""

    hosts: frozenset[tuple[str, int]]

    @classmethod
    def empty(cls) -> "AllowList":
        """Modo "internet desabilitada" (D6): nenhum destino passa."""
        return cls(frozenset())

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, int]]) -> "AllowList":
        return cls(frozenset(pairs))

    def permits(self, host: str, port: int) -> bool:
        return (host.lower(), port) in self.hosts


def _parse_request_line(line: bytes) -> tuple[str, str]:
    """`CONNECT host:porta HTTP/1.1` ou `GET http://host/path HTTP/1.1`."""
    try:
        method, target, _version = line.decode("ascii", errors="strict").rstrip("\r\n").split(" ", 2)
    except ValueError as exc:
        raise ProtocolError(f"primeira linha malformada: {line!r}") from exc
    if not method or not target:
        raise ProtocolError(f"primeira linha malformada: {line!r}")
    return method, target


def _parse_connect_target(target: str) -> tuple[str, int]:
    try:
        host, port_s = target.rsplit(":", 1)
        return host, int(port_s)
    except ValueError as exc:
        raise ProtocolError(f"alvo de CONNECT malformado: {target!r}") from exc


def _parse_absolute_target(target: str) -> tuple[str, int, str]:
    """`http://host[:porta]/path` — forma que o `HTTP_PROXY` dos clientes usa
    pra requisição em texto puro (não-`CONNECT`)."""
    parsed = urlparse(target)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ProtocolError(f"alvo HTTP absoluto malformado: {target!r}")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname, parsed.port or 80, path


async def _consume_headers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            return


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    """Repassa até o EOF de `src` e então faz um *half-close* em `dst`
    (`write_eof`, não `close`) — um `close()` aqui derrubaria o socket
    inteiro, inclusive a direção contrária que `_relay` ainda pode estar
    lendo (achado real: um pump terminando cedo cortava a resposta que
    ainda estava a caminho pela outra metade da mesma conexão)."""
    try:
        while True:
            chunk = await src.read(_READ_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        if dst.can_write_eof():
            dst.write_eof()
        else:
            dst.close()


async def _refuse(writer: asyncio.StreamWriter, code: int, reason: str) -> None:
    writer.write(f"HTTP/1.1 {code} {reason}\r\n\r\n".encode())
    await writer.drain()
    writer.close()


async def _relay(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                 host: str, port: int) -> None:
    """Abre a conexão upstream e repassa bytes nos dois sentidos sem olhar o
    conteúdo — chamado só depois que o destino já passou pela allow-list."""
    try:
        up_reader, up_writer = await asyncio.open_connection(host, port)
    except OSError:
        await _refuse(client_writer, 502, "Bad Gateway")
        return
    await asyncio.gather(
        _pump(client_reader, up_writer),
        _pump(up_reader, client_writer),
    )
    up_writer.close()
    client_writer.close()


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                        allow_list: AllowList, log=print) -> None:
    """Uma conexão do cliente: `CONNECT` abre túnel cego; requisição HTTP
    absoluta é repassada como texto. Qualquer destino fora da `allow_list`
    é recusado antes de qualquer tentativa de conexão upstream."""
    try:
        line = await client_reader.readline()
        if not line:
            client_writer.close()
            return
        method, target = _parse_request_line(line)
        await _consume_headers(client_reader)

        if method == "CONNECT":
            host, port = _parse_connect_target(target)
            if not allow_list.permits(host, port):
                log("RECUSADO (CONNECT):", f"{host}:{port}")
                await _refuse(client_writer, 403, "Forbidden")
                return
            log("permitido (CONNECT):", f"{host}:{port}")
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            await _relay(client_reader, client_writer, host, port)
            return

        host, port, path = _parse_absolute_target(target)
        if not allow_list.permits(host, port):
            log("RECUSADO (HTTP):", f"{host}:{port}")
            await _refuse(client_writer, 403, "Forbidden")
            return
        log("permitido (HTTP):", f"{host}:{port}")
        try:
            up_reader, up_writer = await asyncio.open_connection(host, port)
        except OSError:
            await _refuse(client_writer, 502, "Bad Gateway")
            return
        up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode())
        up_writer.write(f"Host: {host}\r\n".encode())
        up_writer.write(b"Connection: close\r\n\r\n")
        await up_writer.drain()
        await _pump(up_reader, client_writer)
    except ProtocolError as exc:
        log("protocolo invalido:", exc)
        await _refuse(client_writer, 400, "Bad Request")
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass


async def serve(listen_host: str, listen_port: int, allow_list: AllowList, log=print) -> None:
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, allow_list, log), listen_host, listen_port
    )
    log(f"escutando {listen_host}:{listen_port} — {len(allow_list.hosts)} destino(s) na allow-list")
    async with server:
        await server.serve_forever()
