"""E2E browser: gate de banco no data plane (task 8.5, change
db-proxy-gate-data-plane) — cobre "o caminho novo", diferente de
`test_gate.py` (que simula o gate antigo via texto casado pelo harness fake,
sem nenhum SQL de verdade rodando).

`bloqueada` e `confirmável` em modo enforce nunca pedem aprovação — o proxy
recusa as duas na hora (decisão do operador: achado ao vivo de que o card
de aprovação genérico deixava passar disfarces de SQL destrutivo). O que
resta provar aqui é que (1) a recusa realmente impede a escrita e (2) ela
aparece no chat, não só na auditoria silenciosa.

O harness fake não executa bash nenhum, então não há como chegar no SQL real
por uma mensagem de chat. Em vez disso, este teste:
1) manda uma mensagem que o harness fake reconhece como destrutiva
   (`TRUNCATE`), só para deixar a *run* do sistema em `awaiting_approval` —
   é essa run ativa que `gate._active_run_id` usa para amarrar a notificação
   (origem `agente`) ao chat, exatamente como aconteceria com o harness real
   executando algo que toca o proxy;
2) com a run presa nesse estado, dispara a statement de verdade por dentro
   do container do sistema, via `asyncpg` contra o listener do sidecar —
   isso sim atravessa o protocolo real do Postgres;
3) verifica que a `DELETE` falha na hora (nunca chega ao banco) e que o chat
   mostra a notificação de bloqueio com a query à mostra.

Modo enforce é obrigatório para isto (sombra nunca segura nada) — como
`db_gate_mode` é env var do processo do portal, não dá pra mudar em
runtime: a fixture `enforce_portal` recria só o serviço `portal` do stack
E2E dedicado com a env trocada, e devolve ao default (sombra) no teardown.
"""

import os
import pathlib
import subprocess
import time
import uuid

import httpx
import pytest
from catalog_flow import activate, create_catalog_connection, grant, open_system_connections, pick

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@appaiforge.local"
ADMIN_PASSWORD = "admin123"
BASE_URL = os.environ.get("APPAIFORGE_E2E_BASE_URL", "http://localhost:8081").rstrip("/")
PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_PG_CONTAINER", "appaiforge-e2e-postgres-1")
COMPOSE_FILE = pathlib.Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.e2e.yml"


def _docker():
    import docker

    return docker.from_env()


def _compose(*args: str, env: dict | None = None) -> None:
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True, text=True, env=full_env, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} falhou: {result.stderr.strip()}")


def _wait_portal_healthy(deadline_s: int = 60) -> None:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/api/health", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("portal não voltou saudável a tempo")


@pytest.fixture(scope="module")
def enforce_portal():
    """Recria só o `portal` do stack E2E dedicado em modo enforce (D4 do
    design: `db_gate_mode` decide no boot do processo, não por request).
    Nunca aponta para o ambiente real — é o mesmo `docker-compose.e2e.yml`
    isolado que o resto da suíte usa."""
    _compose("up", "-d", "portal", env={"APPAIFORGE_DB_GATE_MODE": "enforce"})
    _wait_portal_healthy()
    yield
    _compose("up", "-d", "portal")  # sem override -> volta ao default do compose (sombra)
    _wait_portal_healthy()


@pytest.fixture()
def suffix() -> str:
    return uuid.uuid4().hex[:8]


def _login(page, email: str, password: str) -> None:
    page.goto("/login")
    page.locator('[data-testid=login-email]').fill(email)
    page.locator('[data-testid=login-password]').fill(password)
    page.get_by_role("button", name="Entrar").click()
    page.locator('[data-testid=user-menu]').wait_for(timeout=30_000)


def _logout(page) -> None:
    page.locator('[data-testid=user-menu]').click()
    page.locator('[data-testid=logout]').click()
    page.get_by_role("button", name="Entrar").wait_for(timeout=30_000)


def _create_system(page, suffix: str) -> str:
    editor_email = f"dbgate-e2e-{suffix}@e2e.local"
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    page.get_by_role("button", name="Administração").click()
    page.get_by_role("button", name="Novo usuário").click()
    page.locator('[data-testid=new-user-email]').fill(editor_email)
    page.locator('[data-testid=new-user-password]').fill("pw-dbgate")
    page.locator('[data-testid=new-user-type]').click()
    page.locator('.q-menu:visible').get_by_text("editor", exact=True).click()
    page.locator('[data-testid=create-user]').click()
    page.get_by_text(editor_email).first.wait_for(timeout=30_000)
    _logout(page)

    _login(page, editor_email, "pw-dbgate")
    page.get_by_role("button", name="Novo sistema").click()
    slug = f"dbgate-{suffix}"
    page.locator('[data-testid=system-name]').fill("Sistema DbGate E2E")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    page.get_by_role("tab", name="Chat").wait_for(timeout=60_000)

    deadline = time.time() + 60
    while time.time() < deadline:
        if "ativo" in page.locator(".q-badge").all_inner_texts():
            return slug
        page.wait_for_timeout(1000)
    raise AssertionError("provisionamento não concluiu")


def _register_vendas_connection(page, slug: str, suffix: str, ceiling: str | None = None,
                                mode: str | None = None) -> str:
    """Catálogo (change add-db-manager-role): o admin cadastra o banco `appaiforge2` do stack e
    autoriza para o sistema; o dono ativa com o alias `vendas`. Volta logado como o dono, na
    aba Conexões do sistema. Devolve o nome da conexão no catálogo."""
    editor_email = f"dbgate-e2e-{suffix}@e2e.local"
    conn_name = f"vendas-gate-{suffix}"
    _logout(page)
    _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    create_catalog_connection(page, conn_name, "appaiforge2")
    grant(page, conn_name, slug, ceiling)
    _logout(page)
    _login(page, editor_email, "pw-dbgate")
    open_system_connections(page, slug)
    activate(page, conn_name, "vendas", mode)
    return conn_name


def _psql(sql: str) -> None:
    result = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-d", "appaiforge2", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql falhou: {result.stderr.strip()}")


def _wait_sidecar_running(slug: str) -> None:
    import docker as docker_sdk

    name = f"appaiforge-sys-{slug}-dbgate"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            sidecar = _docker().containers.get(name)
            if sidecar.status == "running":
                return
        except docker_sdk.errors.NotFound:
            pass
        time.sleep(1)
    raise AssertionError(f"sidecar {name} não subiu em 60s")


def _sidecar_id(slug: str) -> str | None:
    import docker as docker_sdk

    try:
        return _docker().containers.get(f"appaiforge-sys-{slug}-dbgate").id
    except docker_sdk.errors.NotFound:
        return None


def _wait_sidecar_replaced(slug: str, old_id: str | None) -> None:
    """Mudar o modo recria o container do sistema e o sidecar (design D7)."""
    deadline = time.time() + 90
    while time.time() < deadline:
        current = _sidecar_id(slug)
        if current and current != old_id:
            _wait_sidecar_running(slug)
            return
        time.sleep(1)
    raise AssertionError("o sidecar não foi recriado depois da mudança de modo")


def _sql_via_proxy(slug: str, port: int, sql: str):
    """Executa `sql` de dentro do container do sistema contra uma porta de loopback do sidecar:
    15400 é o listener do agente e 15401 o da app, na primeira conexão do manifesto."""
    container = _docker().containers.get(f"appaiforge-sys-{slug}")
    script = (
        "import asyncio, asyncpg\n"
        "async def main():\n"
        f"    conn = await asyncpg.connect(host='127.0.0.1', port={port}, user='x', password='x', "
        "database='appaiforge2')\n"
        f"    print(await conn.execute({sql!r}))\n"
        "    await conn.close()\n"
        "asyncio.run(main())\n"
    )
    return container.exec_run(["python3", "-c", script])


def _delete_via_proxy(slug: str):
    """Executa `DELETE FROM clientes` de dentro do container do sistema via
    `asyncpg` contra a porta de loopback do sidecar (origem `agente`, task
    5.1: primeira e única conexão do manifesto cai em DB_GATE_PORT_BASE =
    15400) — é isto que atravessa o protocolo real do Postgres, não o
    harness fake."""
    container = _docker().containers.get(f"appaiforge-sys-{slug}")
    script = (
        "import asyncio, asyncpg\n"
        "async def main():\n"
        "    conn = await asyncpg.connect(host='127.0.0.1', port=15400, user='agent', password='x', database='appaiforge2')\n"
        "    result = await conn.execute('DELETE FROM clientes')\n"
        "    print(result)\n"
        "    await conn.close()\n"
        "asyncio.run(main())\n"
    )
    return container.exec_run(["python3", "-c", script])


def test_confirmavel_em_enforce_e_recusada_direto_e_avisa_no_chat(enforce_portal, page, suffix):
    slug = _create_system(page, suffix)
    _register_vendas_connection(page, slug, suffix)
    _wait_sidecar_running(slug)

    _psql("DROP TABLE IF EXISTS clientes")
    _psql("CREATE TABLE clientes (id serial primary key, nome text)")
    _psql("INSERT INTO clientes (nome) VALUES ('ana'), ('bruno')")

    page.get_by_role("tab", name="Chat").click()

    # mensagem que o harness fake reconhece como confirmável (TRUNCATE é DDL
    # e o gate antigo bloqueia automaticamente, sem card — precisa ser
    # "DELETE SEM WHERE", a mesma frase de test_gate.py): só serve pra
    # deixar a run do sistema em awaiting_approval (card antigo, control
    # plane) — é essa run ativa que o proxy usa para amarrar a notificação
    # ao chat; o SQL de verdade do teste não passa por aqui.
    page.locator('[data-testid=chat-input]').fill("agora DELETE SEM WHERE na tabela clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("PEDIDO DE APROVAÇÃO").wait_for(timeout=60_000)

    result = _delete_via_proxy(slug)
    output = result.output.decode()
    assert result.exit_code != 0, output  # recusada na hora, sem pedir aprovação
    assert "sem WHERE" in output

    # a recusa aparece ao vivo no chat, com a query bloqueada à mostra —
    # não só na auditoria silenciosa (correção pedida pelo operador)
    page.get_by_text("bloqueada pelo proxy de banco").wait_for(timeout=10_000)
    page.get_by_text("DELETE FROM clientes").first.wait_for(timeout=5_000)

    # resolve o pedido antigo (TRUNCATE) pra run do harness fake terminar limpa
    page.locator('[data-testid=gate-deny]').click()
    page.get_by_text("agente livre").wait_for(timeout=60_000)

    page.get_by_role("tab", name="Auditoria").click()
    page.get_by_text("Gate de destrutivas").wait_for(timeout=30_000)
    page.get_by_text("DELETE FROM clientes").first.wait_for(timeout=30_000)


def test_schema_admin_libera_ddl_so_para_o_agente(enforce_portal, page, suffix):
    """change add-db-manager-role, task 6.5: com a conexão em `schema_admin` o agente executa
    DDL e a app tem a mesma statement recusada; rebaixado o modo, o agente volta a ser recusado."""
    slug = _create_system(page, suffix)
    _register_vendas_connection(page, slug, suffix, ceiling="Leitura, escrita e DDL",
                                mode="Leitura, escrita e DDL")
    _wait_sidecar_running(slug)
    table = f"ddl_{suffix}"
    _psql(f"DROP TABLE IF EXISTS {table}")
    _psql(f"CREATE TABLE {table} (id int)")

    app_try = _sql_via_proxy(slug, 15401, f"DROP TABLE {table}")
    assert app_try.exit_code != 0, app_try.output.decode()  # listener da app: recusada

    agent_try = _sql_via_proxy(slug, 15400, f"DROP TABLE {table}")
    assert agent_try.exit_code == 0, agent_try.output.decode()  # listener do agente: liberada

    # o selo de DDL liberada aparece para o dono, e a decisão fica no histórico do gate
    card = page.locator('[data-testid="conn-card:vendas-gate-%s"]' % suffix)
    card.locator('[data-testid=ddl-since]').wait_for(timeout=10_000)
    page.get_by_role("tab", name="Auditoria").click()
    page.locator('[data-testid="gate-decision:liberada"]').first.wait_for(timeout=30_000)

    # o dono rebaixa para leitura e escrita: o sidecar é recriado e o agente volta a ser recusado
    old_sidecar = _sidecar_id(slug)
    page.get_by_role("tab", name="Conexões").click()
    card.locator('[data-testid=conn-change-mode]').click()
    pick(page, "change-mode", "Leitura e escrita")
    page.locator('[data-testid=confirm-change-mode]').click()
    _wait_sidecar_replaced(slug, old_sidecar)
    _psql(f"CREATE TABLE IF NOT EXISTS {table} (id int)")
    again = _sql_via_proxy(slug, 15400, f"DROP TABLE {table}")
    assert again.exit_code != 0, again.output.decode()
