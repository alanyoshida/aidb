"""E2E browser: gate de banco no data plane (task 8.5, change
db-proxy-gate-data-plane) — cobre "o caminho novo", diferente de
`test_gate.py` (que simula o gate antigo via texto casado pelo harness fake,
sem nenhum SQL de verdade rodando).

O harness fake não executa bash nenhum, então não há como chegar no SQL real
por uma mensagem de chat. Em vez disso, este teste:
1) manda uma mensagem que o harness fake reconhece como destrutiva
   (`TRUNCATE`), só para deixar a *run* do sistema em `awaiting_approval` —
   é essa run ativa que `gate._active_run_id` usa para amarrar o pedido novo
   (origem `agente`) ao chat, exatamente como aconteceria com o harness real
   executando algo que toca o proxy;
2) com a run presa nesse estado, dispara a statement de verdade por dentro
   do container do sistema, via `asyncpg` contra o listener do sidecar —
   isso sim atravessa o protocolo real do Postgres;
3) verifica que o card NOVO (`dbgate-approve`, distinto do card antigo
   `gate-approve`) aparece no chat e que aprová-lo libera a conexão de
   verdade (a `DELETE` executa e o audit mostra "aprovada").

Modo enforce é obrigatório para isto (sombra nunca segura nada) — como
`db_gate_mode` é env var do processo do portal, não dá pra mudar em
runtime: a fixture `enforce_portal` recria só o serviço `portal` do stack
E2E dedicado com a env trocada, e devolve ao default (sombra) no teardown.
"""

import os
import pathlib
import subprocess
import threading
import time
import uuid

import httpx
import pytest

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


def _register_vendas_connection(page) -> None:
    page.get_by_role("tab", name="Conexões").click()
    page.get_by_role("button", name="Nova conexão").click()
    page.locator('[data-testid=conn-name]').wait_for(state="visible", timeout=30_000)
    page.locator('[data-testid=conn-name]').fill("vendas")
    page.locator('[data-testid=conn-host]').fill("postgres")
    page.locator('[data-testid=conn-port]').fill("5432")
    page.locator('[data-testid=conn-database]').fill("appaiforge2")
    page.locator('[data-testid=conn-user]').fill("appaiforge")
    page.locator('[data-testid=conn-password]').fill("appaiforge")
    page.locator('[data-testid=save-connection]').click()
    page.get_by_text("conexão cadastrada").wait_for(timeout=20_000)


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


def test_statement_real_e_segurada_e_liberada_pelo_card_novo_do_chat(enforce_portal, page, suffix):
    slug = _create_system(page, suffix)
    _register_vendas_connection(page)
    _wait_sidecar_running(slug)

    _psql("DROP TABLE IF EXISTS clientes")
    _psql("CREATE TABLE clientes (id serial primary key, nome text)")
    _psql("INSERT INTO clientes (nome) VALUES ('ana'), ('bruno')")

    page.get_by_role("tab", name="Chat").click()

    # mensagem que o harness fake reconhece como confirmável (TRUNCATE é DDL
    # e o gate antigo bloqueia automaticamente, sem card — precisa ser
    # "DELETE SEM WHERE", a mesma frase de test_gate.py): só serve pra
    # deixar a run do sistema em awaiting_approval (card antigo, control
    # plane) — é essa run ativa que o proxy usa para amarrar o pedido novo
    # ao chat; o SQL de verdade do teste não passa por aqui.
    page.locator('[data-testid=chat-input]').fill("agora DELETE SEM WHERE na tabela clientes")
    page.locator('[data-testid=chat-send]').click()
    page.get_by_text("PEDIDO DE APROVAÇÃO").wait_for(timeout=60_000)

    result_holder: dict = {}

    def _run_delete():
        result_holder["result"] = _delete_via_proxy(slug)

    thread = threading.Thread(target=_run_delete)
    thread.start()

    # card novo (proxy de banco), distinto do antigo (gate-approve) — os
    # dois ficam visíveis ao mesmo tempo
    page.locator('[data-testid=dbgate-approve]').wait_for(timeout=30_000)
    page.get_by_text("proxy de banco").wait_for(timeout=5_000)
    page.get_by_text("DELETE FROM clientes").first.wait_for(timeout=5_000)
    page.locator('[data-testid=gate-approve]').wait_for(timeout=5_000)  # o antigo não some

    page.locator('[data-testid=dbgate-approve]').click()

    thread.join(timeout=30)
    assert "result" in result_holder, "exec_run não terminou a tempo da aprovação"
    output = result_holder["result"].output.decode()
    assert result_holder["result"].exit_code == 0, output

    # resolve o pedido antigo (TRUNCATE) pra run do harness fake terminar limpa
    page.locator('[data-testid=gate-deny]').click()
    page.get_by_text("agente livre").wait_for(timeout=60_000)

    page.get_by_role("tab", name="Auditoria").click()
    page.get_by_text("Gate de destrutivas").wait_for(timeout=30_000)
    page.get_by_text("DELETE FROM clientes").first.wait_for(timeout=30_000)
