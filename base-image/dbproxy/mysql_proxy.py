"""Proxy de wire protocol MySQL (etapa 4 do confinamento, change db-proxy-gate-data-plane).

Framing e autenticação (task 3.1/3.2): handshake do servidor em loopback
(trust — sem senha real do cliente), autenticação upstream com a credencial
real (`mysql_native_password` e `caching_sha2_password`, incl. full auth
RSA-OAEP-SHA1) e repasse de mensagens — validado no spike (ver design.md) e
replicado aqui como código de produção, com a correção de framing que o
spike encontrou: o scramble do `AuthSwitchRequest` tem 20 bytes
(`SCRAMBLE_LENGTH`), não os bytes inteiros do resto do pacote.

Gate no wire protocol (task 3.1): toda `COM_QUERY` e `COM_STMT_PREPARE`
(que carrega o texto SQL) é classificada com o `sqlgate` canônico, mesma
lógica do proxy Postgres (`pg_proxy.py`). Diferença de framing relevante: o
protocolo MySQL é estritamente requisição-resposta — não há pipelining de
Bind/Execute como no protocolo estendido do Postgres, então bloquear ou
segurar um `COM_STMT_PREPARE` não precisa de máquina de descarte até um
"Sync": um `ERR_Packet` no lugar do `COM_STMT_PREPARE_OK` já é a resposta
completa, e o cliente nunca manda `COM_STMT_EXECUTE` para um id que não
veio. `COM_STMT_EXECUTE` só referencia o id já classificado no `PREPARE` —
sem SQL novo a inspecionar.

`confirmável` segura a conexão e consulta o portal (mesmo `portal_gate.py`
do proxy Postgres, task 2.3/4.1) antes de liberar ou recusar.

Cada instância serve UMA conexão registrada: user/database do cliente no
handshake são sempre sobrescritos pelos da credencial real (injeção de
credencial).

Uso: DATABASE_URL_UPSTREAM="mysql://user:pass@host:porta/db" \
     SYSTEM_ID=<id> LISTEN_PORT=13306 python3 mysql_proxy.py
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import os
import struct
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlgate import Blocked, Confirmable, classify  # noqa: E402  (cópia embarcada do classificador)
import portal_gate  # noqa: E402

GateContext = portal_gate.GateContext

# capabilities (subconjunto suficiente pro handshake trust + auth upstream real)
LONG_PASSWORD = 0x00000001
CONNECT_WITH_DB = 0x00000008
PROTOCOL_41 = 0x00000200
TRANSACTIONS = 0x00002000
SECURE_CONNECTION = 0x00008000
MULTI_RESULTS = 0x00020000
PLUGIN_AUTH = 0x00080000

SERVER_CAPS = LONG_PASSWORD | PROTOCOL_41 | TRANSACTIONS | SECURE_CONNECTION | PLUGIN_AUTH | MULTI_RESULTS
CLIENT_CAPS = SERVER_CAPS | CONNECT_WITH_DB

COM_QUIT = 0x01
COM_INIT_DB = 0x02
COM_QUERY = 0x03
COM_STMT_PREPARE = 0x16

SCRAMBLE_LENGTH = 20


def log(*args) -> None:
    print("[dbproxy-mysql]", *args, flush=True)


@dataclasses.dataclass(frozen=True)
class UpstreamConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_dsn(cls, dsn: str) -> "UpstreamConfig":
        p = urlparse(dsn)
        return cls(
            host=p.hostname or "127.0.0.1",
            port=p.port or 3306,
            user=p.username or "",
            password=p.password or "",
            database=(p.path or "").lstrip("/"),
        )


class ProtocolError(RuntimeError):
    """Mensagem inesperada ou upstream recusou a conexão."""


# ---------- framing ----------

async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """payload com 1 byte de seq + int24 de tamanho (não inclui o header)."""
    header = await reader.readexactly(4)
    length = header[0] | header[1] << 8 | header[2] << 16
    return header[3], await reader.readexactly(length)


def write_packet(writer: asyncio.StreamWriter, seq: int, payload: bytes) -> None:
    n = len(payload)
    writer.write(bytes([n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF, seq & 0xFF]) + payload)


def ok_packet() -> bytes:
    return b"\x00\x00\x00" + struct.pack("<H", 0x0002) + struct.pack("<H", 0)


def err_packet(message: str, errno: int = 1142, sqlstate: str = "42000") -> bytes:
    return b"\xff" + struct.pack("<H", errno) + b"#" + sqlstate.encode() + message.encode()


def server_handshake(seed: bytes) -> bytes:
    return (
        b"\x0a" + b"8.0.42-aidb-proxy\x00"
        + struct.pack("<I", 1)
        + seed[:8] + b"\x00"
        + struct.pack("<H", SERVER_CAPS & 0xFFFF)
        + bytes([45])
        + struct.pack("<H", 0x0002)
        + struct.pack("<H", SERVER_CAPS >> 16)
        + bytes([21])
        + b"\x00" * 10
        + seed[8:] + b"\x00"
        + b"mysql_native_password\x00"
    )


# ---------- autenticação upstream (o proxy como cliente do MySQL real) ----------

def native_token(password: str, seed: bytes) -> bytes:
    if not password:
        return b""
    h1 = hashlib.sha1(password.encode()).digest()
    h2 = hashlib.sha1(h1).digest()
    h3 = hashlib.sha1(seed + h2).digest()
    return bytes(a ^ b for a, b in zip(h1, h3))


def caching_sha2_token(password: str, seed: bytes) -> bytes:
    if not password:
        return b""
    h1 = hashlib.sha256(password.encode()).digest()
    h2 = hashlib.sha256(h1).digest()
    h3 = hashlib.sha256(h2 + seed).digest()
    return bytes(a ^ b for a, b in zip(h1, h3))


# ---------- RSA-OAEP-SHA1 em Python puro (full auth do caching_sha2) ----------

def _read_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        nbytes = length & 0x7F
        length = int.from_bytes(data[pos:pos + nbytes], "big")
        pos += nbytes
    return tag, data[pos:pos + length], pos + length


def parse_rsa_pubkey(pem: bytes) -> tuple[int, int]:
    der = base64.b64decode(b"".join(pem.splitlines()[1:-1]))
    tag, seq, _ = _read_tlv(der, 0)
    assert tag == 0x30
    tag, first, pos = _read_tlv(seq, 0)
    if tag == 0x30:  # SPKI: algoritmo; a chave PKCS#1 vem no BIT STRING seguinte
        tag, bitstr, _ = _read_tlv(seq, pos)
        assert tag == 0x03
        tag, seq, _ = _read_tlv(bitstr[1:], 0)
        assert tag == 0x30
        tag, first, pos = _read_tlv(seq, 0)
    assert tag == 0x02
    tag, e_raw, _ = _read_tlv(seq, pos)
    assert tag == 0x02
    return int.from_bytes(first, "big"), int.from_bytes(e_raw, "big")


def mgf1(seed: bytes, length: int) -> bytes:
    out = b""
    for i in range((length + 19) // 20):
        out += hashlib.sha1(seed + struct.pack(">I", i)).digest()
    return out[:length]


def rsa_oaep_sha1_encrypt(pem: bytes, message: bytes) -> bytes:
    n, e = parse_rsa_pubkey(pem)
    k = (n.bit_length() + 7) // 8
    lhash = hashlib.sha1(b"").digest()
    ps = b"\x00" * (k - len(message) - 2 * 20 - 2)
    db = lhash + ps + b"\x01" + message
    seed = os.urandom(20)
    masked_db = bytes(a ^ b for a, b in zip(db, mgf1(seed, k - 21)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, mgf1(masked_db, 20)))
    em = b"\x00" + masked_seed + masked_db
    c = pow(int.from_bytes(em, "big"), e, n)
    return c.to_bytes(k, "big")


def xor_with_seed(message: bytes, seed: bytes) -> bytes:
    return bytes(b ^ seed[i % len(seed)] for i, b in enumerate(message))


async def upstream_auth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, cfg: UpstreamConfig) -> None:
    seq, hs = await read_packet(reader)
    if hs[0] != 0x0A:
        raise ProtocolError(f"handshake upstream inesperado: {hs[0]:#x}")
    pos = hs.index(b"\x00", 1) + 1
    pos += 4  # connection id
    seed_part1 = hs[pos:pos + 8]
    pos += 8 + 1
    caps_low = struct.unpack("<H", hs[pos:pos + 2])[0]
    pos += 2
    pos += 1 + 2  # charset, status
    caps_high = struct.unpack("<H", hs[pos:pos + 2])[0]
    pos += 2
    caps = caps_low | caps_high << 16
    auth_len = hs[pos]
    pos += 1 + 10
    seed_part2 = b""
    if caps & SECURE_CONNECTION:
        seed_part2 = hs[pos:pos + max(13, auth_len - 8)].rstrip(b"\x00")
        pos += max(13, auth_len - 8)
    plugin = hs[pos:].rstrip(b"\x00").decode() if caps & PLUGIN_AUTH else "mysql_native_password"
    seed = seed_part1 + seed_part2

    def handshake_response(plugin_name: str, token: bytes) -> bytes:
        return (
            struct.pack("<I", CLIENT_CAPS) + struct.pack("<I", 1 << 24) + bytes([45]) + b"\x00" * 23
            + cfg.user.encode() + b"\x00"
            + bytes([len(token)]) + token
            + cfg.database.encode() + b"\x00"
            + plugin_name.encode() + b"\x00"
        )

    token = caching_sha2_token(cfg.password, seed) if plugin == "caching_sha2_password" else native_token(cfg.password, seed)
    write_packet(writer, 1, handshake_response(plugin, token))
    await writer.drain()

    while True:
        seq, payload = await read_packet(reader)
        head = payload[0]
        if head == 0x00:  # OK
            return
        if head == 0xFF:
            raise ProtocolError(f"upstream recusou auth: {payload!r}")
        if head == 0xFE:  # AuthSwitchRequest
            nul = payload.index(b"\x00", 1)
            plugin = payload[1:nul].decode()
            # achado do spike: o scramble vem com um \x00 extra depois dos 20
            # bytes reais — usar o resto inteiro do pacote gera hash errado
            seed = payload[nul + 1:nul + 1 + SCRAMBLE_LENGTH]
            token = caching_sha2_token(cfg.password, seed) if plugin == "caching_sha2_password" else native_token(cfg.password, seed)
            write_packet(writer, seq + 1, token)
            await writer.drain()
            continue
        if head == 0x01:  # AuthMoreData (caching_sha2)
            sub = payload[1]
            if sub == 0x03:  # fast auth success — o OK vem no próximo pacote
                continue
            if sub == 0x04:  # full auth: pede a chave pública e cifra
                write_packet(writer, seq + 1, b"\x02")
                await writer.drain()
                seq, pem_payload = await read_packet(reader)
                if pem_payload[0] != 0x01:
                    raise ProtocolError(f"resposta de chave pública inesperada: {pem_payload[:1]!r}")
                pem = pem_payload[1:]
                scrambled = xor_with_seed(cfg.password.encode() + b"\x00", seed)
                write_packet(writer, seq + 1, rsa_oaep_sha1_encrypt(pem, scrambled))
                await writer.drain()
                continue
            raise ProtocolError(f"AuthMoreData inesperado: {sub:#x}")
        raise ProtocolError(f"pacote inesperado na auth upstream: {head:#x}")


async def connect_upstream(cfg: UpstreamConfig) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection(cfg.host, cfg.port)
    await upstream_auth(reader, writer, cfg)
    return reader, writer


# ---------- gate: extração/classificação/hold (tasks 3.1/2.3 reaproveitada) ----------

def extract_sql(cmd: int, payload: bytes) -> str | None:
    """SQL embutido no comando, se houver: `COM_QUERY`/`COM_STMT_PREPARE`
    carregam o texto puro até o fim do pacote (sem terminador)."""
    if cmd in (COM_QUERY, COM_STMT_PREPARE):
        return payload[1:].decode(errors="replace")
    return None


async def _refuse(client_writer: asyncio.StreamWriter, seq: int, message: str) -> None:
    """`ERR_Packet` é a resposta completa — MySQL não faz pipelining de
    comandos como o protocolo estendido do Postgres, então não há nada
    pendente para descartar."""
    write_packet(client_writer, seq + 1, err_packet(message))
    await client_writer.drain()


async def _pump_client_to_upstream(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                                   up_writer: asyncio.StreamWriter, gate_ctx: GateContext,
                                   gate_mode: str = "shadow") -> None:
    """Classifica `COM_QUERY`/`COM_STMT_PREPARE` com o sqlgate antes de
    repassar. `gate_mode="enforce"`: `bloqueada` nunca chega ao upstream;
    `confirmável` segura a conexão e consulta o portal antes de liberar ou
    recusar. `gate_mode="shadow"` (default, task 6.1): classifica e audita
    sem segurar nada — os globs de `permission.bash` continuam sendo o
    gate de verdade enquanto o spike S5 compara os dois."""
    try:
        while True:
            seq, payload = await read_packet(client_reader)
            cmd = payload[0]
            if cmd == COM_QUIT:
                write_packet(up_writer, seq, payload)
                await up_writer.drain()
                break
            sql = extract_sql(cmd, payload)
            if sql is not None:
                result = classify(sql)
                if isinstance(result, Blocked):
                    if gate_mode != "enforce":
                        log("SOMBRA (seria bloqueada):", sql, "-", result.reason)
                        await portal_gate.audit_shadow(gate_ctx, sql, log=log)
                    else:
                        log("BLOQUEADA:", sql, "-", result.reason)
                        await _refuse(client_writer, seq, result.reason)
                        await portal_gate.audit_shadow(gate_ctx, sql, log=log, enforced=True)
                        continue
                elif isinstance(result, Confirmable):
                    if gate_mode != "enforce":
                        log("SOMBRA (seria confirmável):", sql, "-", result.reason)
                        await portal_gate.audit_shadow(gate_ctx, sql, log=log)
                    else:
                        log("CONFIRMAVEL, segurando:", sql, "-", result.reason)
                        status = await portal_gate.decide_confirmable(gate_ctx, sql, result.reason, log=log)
                        if status != "aprovada":
                            log(f"CONFIRMAVEL {status}:", sql)
                            await _refuse(client_writer, seq, f"statement confirmável {status} (motivo: {result.reason})")
                            continue
                        log("CONFIRMAVEL aprovada:", sql)
                else:
                    log("normal:", sql)
            write_packet(up_writer, seq, payload)
            await up_writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass


async def _pump_upstream_to_client(up_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            seq, payload = await read_packet(up_reader)
            write_packet(client_writer, seq, payload)
            await client_writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        client_writer.close()


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                        cfg: UpstreamConfig, gate_ctx: GateContext, gate_mode: str = "shadow") -> None:
    peer = client_writer.get_extra_info("peername")
    log("conexão de", peer)
    up_writer: asyncio.StreamWriter | None = None
    try:
        seed = os.urandom(20)
        write_packet(client_writer, 0, server_handshake(seed))
        await client_writer.drain()

        seq, response = await read_packet(client_reader)
        if len(response) < 4 + 4 + 1 + 23:
            raise ProtocolError("handshake response do cliente truncada")

        up_reader, up_writer = await connect_upstream(cfg)

        write_packet(client_writer, 2, ok_packet())
        await client_writer.drain()

        client_to_upstream = asyncio.create_task(
            _pump_client_to_upstream(client_reader, client_writer, up_writer, gate_ctx, gate_mode)
        )
        upstream_to_client = asyncio.create_task(_pump_upstream_to_client(up_reader, client_writer))
        await asyncio.wait({client_to_upstream, upstream_to_client}, return_when=asyncio.FIRST_COMPLETED)
        client_to_upstream.cancel()
        upstream_to_client.cancel()
    except ProtocolError as exc:
        log("erro de protocolo:", exc)
        try:
            write_packet(client_writer, 2, err_packet(str(exc)))
            await client_writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        if up_writer is not None:
            up_writer.close()
        client_writer.close()


async def serve(listen_host: str, listen_port: int, cfg: UpstreamConfig, gate_ctx: GateContext,
                gate_mode: str = "shadow") -> None:
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, cfg, gate_ctx, gate_mode), listen_host, listen_port
    )
    log(f"escutando {listen_host}:{listen_port} -> {cfg.host}:{cfg.port}/{cfg.database} (modo {gate_mode})")
    async with server:
        await server.serve_forever()


def main() -> None:
    dsn = os.environ.get("DATABASE_URL_UPSTREAM", "")
    system_id = os.environ.get("SYSTEM_ID", "")
    if not dsn or not system_id:
        print(
            "uso: DATABASE_URL_UPSTREAM=mysql://user:pass@host:porta/db SYSTEM_ID=<id> mysql_proxy.py",
            file=sys.stderr,
        )
        sys.exit(1)
    cfg = UpstreamConfig.from_dsn(dsn)
    gate_ctx = GateContext(
        system_id=system_id,
        origin=os.environ.get("ORIGIN", "agente"),
        connection_name=os.environ.get("CONNECTION_NAME", ""),
    )
    gate_mode = os.environ.get("APPAIFORGE_DB_GATE_MODE", "shadow")
    listen_port = int(os.environ.get("LISTEN_PORT", "13306"))
    listen_host = os.environ.get("LISTEN_HOST", "127.0.0.1")
    asyncio.run(serve(listen_host, listen_port, cfg, gate_ctx, gate_mode))


if __name__ == "__main__":
    main()
