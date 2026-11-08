"""Integração com Docker real do gate de banco no data plane (seção 8,
change db-proxy-gate-data-plane). Cobre o ponta-a-ponta: sistema real,
sidecar real, proxy real falando o protocolo do Postgres e um HTTP mínimo
no lugar do portal completo (as rotas internas do gate, task 4.1) — subir o
NiceGUI/sync do LiteLLM só pra isso seria peso morto.

Requer a imagem base (appaiforge/base:0.1.0) com o dbproxy embarcado.
"""

import socket
import threading
import time

import pytest

pytestmark = pytest.mark.integration

DBGATE_TOKEN = "teste-dbgate-token"


def _client():
    import docker

    return docker.from_env()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _gateway_ip(network_name: str) -> str:
    net = _client().networks.get(network_name)
    return net.attrs["IPAM"]["Config"][0]["Gateway"]


def _build_fake_portal_app():
    """A rota interna de auditoria do gate de banco (main.py), chamando o
    mesmo `gate` de produção contra o banco real do teste — sem subir o
    portal inteiro (NiceGUI, sync do LiteLLM) só pra o sidecar ter quem
    chamar. `bloqueada`/`confirmável` em enforce são recusadas pelo proxy
    por conta própria (sem pedir decisão a um humano); esta rota só
    registra a auditoria depois do fato."""
    import hmac

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from appaiforge import gate
    from appaiforge.config import get_settings

    app = FastAPI()

    def _authorized(request: Request) -> bool:
        expected = get_settings().db_gate_proxy_service_token
        supplied = request.headers.get("x-aidb-dbgate-token", "")
        return bool(expected) and hmac.compare_digest(supplied, expected)

    @app.post("/internal/db-gate/audit")
    async def audit(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "não autorizado"}, status_code=401)
        payload = await request.json()
        gate.record_shadow_decision(
            payload["system_id"], payload["sql"], origin=payload["origin"],
            connection_name=payload.get("connection_name", ""), enforced=bool(payload.get("enforced", False)),
        )
        return JSONResponse({"status": "ok"})

    return app


@pytest.fixture()
def dbgate_portal(docker_env, monkeypatch):
    """Sobe o HTTP mínimo acima e aponta o sidecar pra ele pelo gateway da
    rede Docker — o sidecar é um container real e precisa alcançar isso
    pela rede, não em processo (diferente do resto do portal em teste).

    Devolve o IP do gateway: o Postgres de teste (testcontainers) também só
    é alcançável pelos containers por esse mesmo IP — `live_pg["host"]`
    ("localhost") é relativo ao processo do pytest, não ao netns do
    sistema/sidecar."""
    import httpx
    import uvicorn

    from appaiforge.config import get_settings
    from appaiforge.provisioning import ensure_network

    monkeypatch.setenv("APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN", DBGATE_TOKEN)
    get_settings.cache_clear()
    ensure_network()
    gateway = _gateway_ip(get_settings().docker_network)
    port = _free_port()
    monkeypatch.setenv("APPAIFORGE_PORTAL_INTERNAL_URL", f"http://{gateway}:{port}")
    get_settings.cache_clear()

    config = uvicorn.Config(_build_fake_portal_app(), host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    up = False
    while time.time() < deadline:
        try:
            httpx.post(f"http://127.0.0.1:{port}/internal/db-gate/audit", json={}, timeout=1)
            up = True
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    if not up:
        raise AssertionError("portal fake (rota de auditoria do gate) não subiu em 10s")

    yield gateway
    server.should_exit = True
    thread.join(timeout=5)
    get_settings.cache_clear()


def _wait_sidecar_running(slug: str) -> None:
    from appaiforge.provisioning import dbgate_sidecar_name

    import docker as docker_sdk

    deadline = time.time() + 60
    name = dbgate_sidecar_name(slug)
    while time.time() < deadline:
        try:
            sidecar = _client().containers.get(name)
            if sidecar.status == "running":
                return
        except docker_sdk.errors.NotFound:
            pass
        time.sleep(1)
    raise AssertionError(f"sidecar {name} não subiu em 60s")


def _agent_port_for(system_id: str, connection_name: str = "vendas") -> int:
    from appaiforge.provisioning import db_connections_manifest

    manifest = db_connections_manifest(system_id)
    (entry,) = [m for m in manifest if m["name"] == connection_name]
    return entry["agent_port"]


def _app_port_for(system_id: str, connection_name: str = "vendas") -> int:
    from appaiforge.provisioning import db_connections_manifest

    manifest = db_connections_manifest(system_id)
    (entry,) = [m for m in manifest if m["name"] == connection_name]
    return entry["app_port"]


def _exec_sql_via_proxy(container, port: int, database: str, sql: str) -> "docker.models.containers.ExecResult":  # noqa: F821
    """Executa `sql` de dentro do container, via asyncpg contra o loopback
    do proxy (porta do sidecar) — o proxy ignora usuário/senha do cliente
    (trust), então qualquer valor serve."""
    script = (
        "import asyncio, asyncpg\n"
        "async def main():\n"
        f"    conn = await asyncpg.connect(host='127.0.0.1', port={port}, user='agent', password='x', database={database!r})\n"
        f"    result = await conn.execute({sql!r})\n"
        "    print(result)\n"
        "    await conn.close()\n"
        "asyncio.run(main())\n"
    )
    return container.exec_run(["python3", "-c", script])


def _setup_clientes_table(live_pg) -> None:
    import psycopg

    with psycopg.connect(
        host=live_pg["host"], port=live_pg["port"], dbname=live_pg["database"],
        user=live_pg["username"], password=live_pg["password"], autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS clientes")
            cur.execute("CREATE TABLE clientes (id serial primary key, nome text)")
            cur.execute("INSERT INTO clientes (nome) VALUES ('ana'), ('bruno')")


def _count_clientes(live_pg) -> int:
    import psycopg

    with psycopg.connect(
        host=live_pg["host"], port=live_pg["port"], dbname=live_pg["database"],
        user=live_pg["username"], password=live_pg["password"], autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM clientes")
            return cur.fetchone()[0]


def test_confirmavel_em_enforce_e_recusada_direto_sem_aprovacao(system, dbgate_portal, live_pg, monkeypatch):
    """Task 8.1 (revista): `DELETE FROM clientes` (sem WHERE, confirmável)
    em modo enforce é recusada pelo proxy na hora, sem segurar a conexão
    nem pedir decisão a um humano — mesmo tratamento de uma DDL. Os dados
    continuam intactos."""
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import connections

    monkeypatch.setenv("APPAIFORGE_DB_GATE_MODE", "enforce")
    get_settings.cache_clear()

    _setup_clientes_table(live_pg)
    provision_system(system)
    connections.register_connection(
        system, "vendas", dbgate_portal, live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"],
    )
    _wait_sidecar_running(system.slug)
    agent_port = _agent_port_for(system.id)
    container = _client().containers.get(system_container_name(system.slug))

    result = _exec_sql_via_proxy(container, agent_port, live_pg["database"], "DELETE FROM clientes")
    output = result.output.decode()
    assert result.exit_code != 0, output  # recusada: o cliente recebe um erro, não um resultado
    assert "sem WHERE" in output or "42501" in output
    assert _count_clientes(live_pg) == 2  # dados intactos

    from appaiforge import gate

    decisions = gate.list_decisions(system.id)
    assert any(
        d["sql"] == "DELETE FROM clientes" and d["decision"] == "bloqueada" and d["classification"] == "confirmavel"
        for d in decisions
    )


def test_modo_sombra_executa_tudo_e_so_audita(system, dbgate_portal, live_pg, monkeypatch):
    """Task 8.2: modo sombra não segura nem bloqueia nada — só audita o que
    teria acontecido em cada classificação. Shadow não é mais o default da
    plataforma (task 7.3) — monkeypatch explícito aqui."""
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import connections

    monkeypatch.setenv("APPAIFORGE_DB_GATE_MODE", "shadow")
    get_settings.cache_clear()

    _setup_clientes_table(live_pg)
    provision_system(system)
    connections.register_connection(
        system, "vendas", dbgate_portal, live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"],
    )
    _wait_sidecar_running(system.slug)
    agent_port = _agent_port_for(system.id)
    container = _client().containers.get(system_container_name(system.slug))

    result = _exec_sql_via_proxy(container, agent_port, live_pg["database"], "DELETE FROM clientes")
    assert result.exit_code == 0, result.output.decode()
    assert _count_clientes(live_pg) == 0  # nada bloqueado: a statement passou de verdade

    from appaiforge import gate

    decisions = gate.list_decisions(system.id)
    assert any(d["sql"] == "DELETE FROM clientes" and d["decision"] == "sombra" for d in decisions)


def test_confirmavel_da_app_registra_origin_distinta_do_agente(system, dbgate_portal, live_pg, monkeypatch):
    """Task 8.3 (revista): a mesma statement confirmável, vinda do listener
    da app (porta "app" do manifesto), é recusada igual à do agente e
    audita com `origin="app"` — distinto do que viria do listener do
    agente, e sem run associado (a app gerada não é uma execução do
    agente)."""
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import connections

    monkeypatch.setenv("APPAIFORGE_DB_GATE_MODE", "enforce")
    get_settings.cache_clear()

    _setup_clientes_table(live_pg)
    provision_system(system)
    connections.register_connection(
        system, "vendas", dbgate_portal, live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"],
    )
    _wait_sidecar_running(system.slug)
    app_port = _app_port_for(system.id)
    container = _client().containers.get(system_container_name(system.slug))

    result = _exec_sql_via_proxy(container, app_port, live_pg["database"], "DELETE FROM clientes")
    assert result.exit_code != 0, result.output.decode()
    assert _count_clientes(live_pg) == 2

    from appaiforge import gate

    decisions = gate.list_decisions(system.id)
    app_decision = next(d for d in decisions if d["sql"] == "DELETE FROM clientes")
    assert app_decision["origin"] == "app"
    assert app_decision["decision"] == "bloqueada"


def test_app_gerada_funciona_pelo_proxy_sem_credencial_no_env(system, dbgate_portal, live_pg):
    """Task 8.4: `DATABASE_URL_<NOME>` do container não carrega credencial
    (loopback puro) e, ainda assim, uma consulta real através dele funciona
    de ponta a ponta — o proxy injeta a credencial de verdade no upstream."""
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import connections

    provision_system(system)
    connections.register_connection(
        system, "vendas", dbgate_portal, live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"],
    )
    _wait_sidecar_running(system.slug)
    container = _client().containers.get(system_container_name(system.slug))

    env_result = container.exec_run(["sh", "-c", "env | grep DATABASE_URL_VENDAS"])
    assert env_result.exit_code == 0, "DATABASE_URL_VENDAS ausente no container"
    env_line = env_result.output.decode().strip()
    dsn = env_line.split("=", 1)[1]
    assert "127.0.0.1" in dsn
    assert "@" not in dsn, "DSN de loopback não deveria carregar user:senha@"

    script = (
        "import asyncio, asyncpg, os\n"
        "from urllib.parse import urlparse\n"
        "async def main():\n"
        "    p = urlparse(os.environ['DATABASE_URL_VENDAS'])\n"
        "    conn = await asyncpg.connect(host=p.hostname, port=p.port, user='agent', password='x', database=p.path.lstrip('/'))\n"
        "    row = await conn.fetchrow('SELECT count(*) FROM clientes')\n"
        "    print(row[0])\n"
        "    await conn.close()\n"
        "asyncio.run(main())\n"
    )
    _setup_clientes_table(live_pg)
    result = container.exec_run(["python3", "-c", script])
    assert result.exit_code == 0, result.output.decode()
    assert "2" in result.output.decode()
