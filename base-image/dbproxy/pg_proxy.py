"""Proxy de wire protocol Postgres v3 (etapa 4 do confinamento, change db-proxy-gate-data-plane).

Framing (task 2.1): startup do cliente (incl. SSLRequest/GSSENCRequest ->
'N'), autenticação trust do lado do servidor em loopback, autenticação com a
credencial real no upstream (SCRAM-SHA-256, md5 ou cleartext) e repasse de
mensagens — validado no spike S8, replicado aqui como código de produção.

Gate no wire protocol (task 2.2): toda `Q` (simple query) e `P` (Parse, que
carrega o texto SQL do protocolo estendido) é classificada com o `sqlgate`
canônico. `bloqueada` nunca chega ao upstream — devolve `ErrorResponse` ao
cliente; no caminho estendido isso exige descartar `Bind`/`Describe`/`Execute`
pipelinados até o `Sync` antes de liberar o `ReadyForQuery` (achado do spike
S8 — sem isso o cliente trava esperando uma resposta por mensagem que nunca
viria).

Hold da confirmável (task 2.3): segura a conexão, registra o pedido no
portal (`portal_gate.py`, endpoint da task 4.1) e faz poll até a decisão do
editor. Aprovada libera a statement; recusada ou expirada vira o mesmo
`ErrorResponse` da bloqueada — do ponto de vista do cliente é indistinguível
de uma recusa automática.

Cada instância serve UMA conexão registrada: user/database do cliente no
startup são sempre sobrescritos pelos da credencial real (injeção de
credencial — o cliente não escolhe identidade, só alcança o que o DSN de
loopback decidir).

Uso: DATABASE_URL_UPSTREAM="postgresql://user:pass@host:porta/db" \
     SYSTEM_ID=<id> LISTEN_PORT=15432 python3 pg_proxy.py
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import hmac
import os
import secrets
import struct
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlgate import Blocked, Confirmable, classify  # noqa: E402  (cópia embarcada do classificador)
import portal_gate  # noqa: E402

SSL_REQUEST = 80877103
GSSENC_REQUEST = 80877104
PROTOCOL_V3 = 196608

AUTH_OK = 0
AUTH_CLEARTEXT = 3
AUTH_MD5 = 5
AUTH_SASL = 10
AUTH_SASL_CONTINUE = 11
AUTH_SASL_FINAL = 12


def log(*args) -> None:
    print("[dbproxy-pg]", *args, flush=True)


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
            port=p.port or 5432,
            user=p.username or "",
            password=p.password or "",
            database=(p.path or "").lstrip("/"),
        )


GateContext = portal_gate.GateContext


class ProtocolError(RuntimeError):
    """Mensagem inesperada ou upstream recusou a conexão."""


# ---------- framing ----------

async def read_message(reader: asyncio.StreamReader) -> bytes:
    """Lê uma mensagem com tag (backend ou frontend pós-startup): 1 byte de tag +
    int32 de tamanho (inclui os 4 bytes do próprio tamanho, não a tag) + payload.
    Devolve a mensagem crua completa (tag+len+payload), pronta pra repasse."""
    header = await reader.readexactly(5)
    length = struct.unpack("!i", header[1:5])[0]
    return header + await reader.readexactly(length - 4)


async def read_startup_packet(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> dict[str, str]:
    """Lê o startup do cliente (sem tag: int32 len + int32 código + payload).
    Responde 'N' a SSLRequest/GSSENCRequest (sem TLS no wire protocol — ver
    design D2/Non-Goals) e repete até receber o StartupMessage real."""
    while True:
        raw_len = await reader.readexactly(4)
        length = struct.unpack("!i", raw_len)[0]
        body = await reader.readexactly(length - 4)
        code = struct.unpack("!i", body[:4])[0]
        if code in (SSL_REQUEST, GSSENC_REQUEST):
            writer.write(b"N")
            await writer.drain()
            continue
        if code != PROTOCOL_V3:
            raise ProtocolError(f"protocolo de startup não suportado: {code}")
        items = body[4:].rstrip(b"\x00").decode().split("\x00")
        return dict(zip(items[::2], items[1::2]))


def encode_startup(params: dict[str, str]) -> bytes:
    body = struct.pack("!i", PROTOCOL_V3)
    for k, v in params.items():
        body += k.encode() + b"\x00" + v.encode() + b"\x00"
    body += b"\x00"
    return struct.pack("!i", 4 + len(body)) + body


def authentication_ok() -> bytes:
    return b"R" + struct.pack("!i", 8) + struct.pack("!i", AUTH_OK)


def ready_for_query() -> bytes:
    return b"Z" + struct.pack("!i", 5) + b"I"


def error_response(message: str, code: str = "08006", severity: str = "FATAL") -> bytes:
    body = (
        b"S" + severity.encode() + b"\x00"
        + b"V" + severity.encode() + b"\x00"
        + b"C" + code.encode() + b"\x00"
        + b"M" + message.encode() + b"\x00"
        + b"\x00"
    )
    return b"E" + struct.pack("!i", 4 + len(body)) + body


# ---------- autenticação upstream (o proxy como cliente do Postgres real) ----------

def _parse_scram_message(data: bytes) -> dict[str, str]:
    return dict(kv.split("=", 1) for kv in data.decode().split(","))


async def _scram_sha256_auth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, password: str) -> None:
    """Fluxo AuthenticationSASL do Postgres (RFC 5802, mecanismo SCRAM-SHA-256)."""
    client_nonce = secrets.token_urlsafe(18)
    client_first_bare = f"n=,r={client_nonce}"
    sasl_init = b"SCRAM-SHA-256\x00" + struct.pack("!i", len(f"n,,{client_first_bare}".encode())) + f"n,,{client_first_bare}".encode()
    writer.write(b"p" + struct.pack("!i", 4 + len(sasl_init)) + sasl_init)
    await writer.drain()

    msg = await read_message(reader)
    if msg[0:1] != b"R" or struct.unpack("!i", msg[5:9])[0] != AUTH_SASL_CONTINUE:
        raise ProtocolError(f"esperava AuthenticationSASLContinue, veio {msg[0:1]!r}")
    server_first = _parse_scram_message(msg[9:])
    full_nonce = server_first["r"]
    if not full_nonce.startswith(client_nonce):
        raise ProtocolError("nonce do servidor não estende o do cliente (possível MITM)")
    salt = base64.b64decode(server_first["s"])
    iterations = int(server_first["i"])

    salted_password = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    client_final_wo_proof = f"c=biws,r={full_nonce}"
    auth_message = f"{client_first_bare},{msg[9:].decode()},{client_final_wo_proof}".encode()
    client_signature = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
    proof = bytes(a ^ b for a, b in zip(client_key, client_signature))
    sasl_response = f"{client_final_wo_proof},p={base64.b64encode(proof).decode()}".encode()
    writer.write(b"p" + struct.pack("!i", 4 + len(sasl_response)) + sasl_response)
    await writer.drain()

    msg = await read_message(reader)
    if msg[0:1] == b"E":
        raise ProtocolError(f"upstream recusou SCRAM: {msg[5:]!r}")
    if msg[0:1] != b"R" or struct.unpack("!i", msg[5:9])[0] != AUTH_SASL_FINAL:
        raise ProtocolError(f"esperava AuthenticationSASLFinal, veio {msg[0:1]!r}")
    server_final = _parse_scram_message(msg[9:])
    server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()
    expected = base64.b64encode(hmac.new(server_key, auth_message, hashlib.sha256).digest()).decode()
    if server_final.get("v") != expected:
        raise ProtocolError("assinatura do servidor não confere no SCRAM-SHA-256 (possível MITM)")


async def _md5_auth(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                    user: str, password: str, salt: bytes) -> None:
    inner = hashlib.md5(password.encode() + user.encode()).hexdigest()
    outer = hashlib.md5(inner.encode() + salt).hexdigest()
    resp = f"md5{outer}".encode() + b"\x00"
    writer.write(b"p" + struct.pack("!i", 4 + len(resp)) + resp)
    await writer.drain()


async def connect_upstream(cfg: UpstreamConfig) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, list[bytes]]:
    """Conecta no Postgres real com a credencial da conexão registrada.
    Devolve (reader, writer, mensagens pós-auth) — ParameterStatus/BackendKeyData
    que o proxy repassa ao cliente como se fossem a própria resposta dele."""
    reader, writer = await asyncio.open_connection(cfg.host, cfg.port)
    writer.write(encode_startup({"user": cfg.user, "database": cfg.database}))
    await writer.drain()

    post_auth: list[bytes] = []
    while True:
        msg = await read_message(reader)
        tag = msg[0:1]
        if tag == b"R":
            code = struct.unpack("!i", msg[5:9])[0]
            if code == AUTH_OK:
                continue
            if code == AUTH_SASL:
                mechanisms = msg[9:].split(b"\x00")
                if b"SCRAM-SHA-256" not in mechanisms:
                    raise ProtocolError(f"upstream não oferece SCRAM-SHA-256: {mechanisms!r}")
                await _scram_sha256_auth(reader, writer, cfg.password)
                continue
            if code == AUTH_MD5:
                await _md5_auth(reader, writer, cfg.user, cfg.password, msg[9:13])
                continue
            if code == AUTH_CLEARTEXT:
                resp = cfg.password.encode() + b"\x00"
                writer.write(b"p" + struct.pack("!i", 4 + len(resp)) + resp)
                await writer.drain()
                continue
            raise ProtocolError(f"método de autenticação upstream não suportado: {code}")
        if tag in (b"S", b"K"):  # ParameterStatus, BackendKeyData
            post_auth.append(msg)
            continue
        if tag == b"Z":  # ReadyForQuery
            return reader, writer, post_auth
        if tag == b"E":
            raise ProtocolError(f"upstream recusou a conexão: {msg[5:]!r}")
        raise ProtocolError(f"mensagem inesperada no startup upstream: {tag!r}")


# ---------- relay (sem classificação — tasks 2.2/2.3 inspecionam Q/P aqui) ----------

async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            msg = await read_message(src)
            dst.write(msg)
            await dst.drain()
            if msg[0:1] == b"X":  # Terminate (frontend) — fecha os dois lados
                break
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass


def extract_sql(tag: bytes, payload: bytes) -> str | None:
    """SQL embutido na mensagem, se houver: `Q` (simple query, string<NUL>
    única) ou `P` (Parse — nome<NUL> + query<NUL> + tipos dos params, só o
    texto interessa à classificação)."""
    if tag == b"Q":
        return payload.rstrip(b"\x00").decode(errors="replace")
    if tag == b"P":
        nul = payload.index(b"\x00")
        rest = payload[nul + 1:]
        return rest[:rest.index(b"\x00")].decode(errors="replace")
    return None


async def _refuse(client_writer: asyncio.StreamWriter, tag: bytes, message: str) -> bool:
    """`ErrorResponse` ao cliente; `Q` fecha com `ReadyForQuery` na hora, `P`
    entra em descarte até o `Sync` (ver docstring do pump). Devolve o novo
    valor de `discarding`."""
    client_writer.write(error_response(message, code="42501", severity="ERROR"))
    if tag == b"Q":
        client_writer.write(ready_for_query())
        await client_writer.drain()
        return False
    await client_writer.drain()
    return True


async def _pump_client_to_upstream(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                                   up_writer: asyncio.StreamWriter, gate_ctx: GateContext,
                                   gate_mode: str = "shadow") -> None:
    """Classifica `Q`/`Parse` com o sqlgate antes de repassar.

    `gate_mode="enforce"`: `bloqueada` nunca chega ao upstream; um `Parse`
    bloqueado ou uma `confirmável` não aprovada entram em modo de descarte
    (Bind/Describe/Execute pipelinados somem) até o `Sync`, só então o
    `ReadyForQuery` libera o cliente — mesma recuperação de erro do
    protocolo estendido real do Postgres. `confirmável` segura a conexão e
    consulta o portal (task 2.3) antes de liberar ou recusar.

    `gate_mode="shadow"` (default, task 6.1): classifica e audita no portal
    (sem segurar nada — `bloqueada`/`confirmável` passam igual à `normal`);
    os globs de `permission.bash` e o `reply_gate` do harness continuam
    sendo o gate de verdade enquanto o spike S5 compara os dois."""
    discarding = False
    try:
        while True:
            msg = await read_message(client_reader)
            tag = msg[0:1]
            if tag == b"X":  # Terminate — fecha os dois lados independente do estado
                up_writer.write(msg)
                await up_writer.drain()
                break
            if discarding:
                if tag == b"S":  # Sync fecha o ciclo estendido em erro
                    discarding = False
                    client_writer.write(ready_for_query())
                    await client_writer.drain()
                continue
            sql = extract_sql(tag, msg[5:])
            if sql is not None:
                result = classify(sql)
                if isinstance(result, Blocked):
                    if gate_mode != "enforce":
                        log("SOMBRA (seria bloqueada):", sql, "-", result.reason)
                        await portal_gate.audit_shadow(gate_ctx, sql, log=log)
                    else:
                        log("BLOQUEADA:", sql, "-", result.reason)
                        discarding = await _refuse(client_writer, tag, result.reason)
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
                            discarding = await _refuse(
                                client_writer, tag, f"statement confirmável {status} (motivo: {result.reason})"
                            )
                            continue
                        log("CONFIRMAVEL aprovada:", sql)
                else:
                    log("normal:", sql)
            up_writer.write(msg)
            await up_writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                        cfg: UpstreamConfig, gate_ctx: GateContext, gate_mode: str = "shadow") -> None:
    peer = client_writer.get_extra_info("peername")
    log("conexão de", peer)
    up_writer: asyncio.StreamWriter | None = None
    try:
        await read_startup_packet(client_reader, client_writer)
        up_reader, up_writer, post_auth = await connect_upstream(cfg)

        client_writer.write(authentication_ok())
        for msg in post_auth:
            client_writer.write(msg)
        client_writer.write(ready_for_query())
        await client_writer.drain()

        client_to_upstream = asyncio.create_task(
            _pump_client_to_upstream(client_reader, client_writer, up_writer, gate_ctx, gate_mode)
        )
        upstream_to_client = asyncio.create_task(_pump(up_reader, client_writer))
        await asyncio.wait({client_to_upstream, upstream_to_client}, return_when=asyncio.FIRST_COMPLETED)
        client_to_upstream.cancel()
        upstream_to_client.cancel()
    except ProtocolError as exc:
        log("erro de protocolo:", exc)
        try:
            client_writer.write(error_response(str(exc)))
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
            "uso: DATABASE_URL_UPSTREAM=postgresql://user:pass@host:porta/db SYSTEM_ID=<id> pg_proxy.py",
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
    listen_port = int(os.environ.get("LISTEN_PORT", "15432"))
    listen_host = os.environ.get("LISTEN_HOST", "127.0.0.1")
    asyncio.run(serve(listen_host, listen_port, cfg, gate_ctx, gate_mode))


if __name__ == "__main__":
    main()
