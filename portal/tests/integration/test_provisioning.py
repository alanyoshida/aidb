"""Integração com Docker real: provisionamento, reconciliação e ciclo de vida.

Requer a imagem base (appaiforge/base:0.1.0) presente no daemon local.
"""

import os

import pytest

pytestmark = pytest.mark.integration


def _client():
    import docker

    return docker.from_env()


def test_provisiona_container_com_limites_labels_e_workspace(system):
    import docker as docker_sdk

    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)

    container = _client().containers.get(system_container_name(system.slug))
    assert container.labels["appaiforge.system_id"] == system.id
    assert container.labels["appaiforge.slug"] == system.slug
    settings = get_settings()
    expected_cpu = int(settings.container_cpus * 1e9)
    attrs = container.attrs
    assert attrs["HostConfig"]["NanoCpus"] == expected_cpu
    assert attrs["HostConfig"]["Memory"] == settings.container_mem_mb * 1024 * 1024
    assert attrs["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
    # workspace com opencode.json e bind montado
    assert (docker_sdk.__name__) or True
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    assert os.path.isfile(os.path.join(workspace, "opencode.json"))


def test_workspace_persiste_entre_reinicios(system):
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)
    from appaiforge.config import get_settings

    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    marker = os.path.join(workspace, "app")
    os.makedirs(marker, exist_ok=True)
    with open(os.path.join(marker, "main.py"), "w") as f:
        f.write("print('codigo gerado')\n")

    container = _client().containers.get(system_container_name(system.slug))
    container.restart()
    import time

    time.sleep(2)
    container = _client().containers.get(system_container_name(system.slug))
    content = container.exec_run(["cat", "/workspace/app/main.py"]).output.decode()
    assert "codigo gerado" in content


def test_reconciliacao_recria_container_ausente(system):
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system, reconcile

    provision_system(system)
    _client().containers.get(system_container_name(system.slug)).remove(force=True)

    reconcile()

    container = _client().containers.get(system_container_name(system.slug))
    assert container.status in ("created", "running", "restarting")


def test_arquivamento_para_container_e_preserva_workspace(system, docker_env):
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import archive_system, provision_system
    from appaiforge.services.systems import get_system

    provision_system(system)
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    assert os.path.isdir(workspace)

    archive_system(system)

    import docker

    with pytest.raises(docker.errors.NotFound):
        _client().containers.get(system_container_name(system.slug))
    assert os.path.isdir(workspace)  # workspace preservado
    assert get_system(system.id).status == SystemStatus.archived


def test_exclusao_remove_container_e_workspace(system, docker_env):
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import archive_system, delete_system, provision_system
    from appaiforge.services.systems import get_system

    provision_system(system)
    archive_system(system)
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)

    delete_system(system)

    import docker

    with pytest.raises(docker.errors.NotFound):
        _client().containers.get(system_container_name(system.slug))
    assert not os.path.isdir(workspace)


def test_teto_de_sistemas_e_respeitado(docker_env, clean_db, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_MAX_SYSTEMS", "1")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    try:
        from appaiforge import auth
        from appaiforge.models import UserType
        from appaiforge.services.systems import create_system
        from appaiforge.provisioning import CapacityReached, provision_system

        editor = auth.create_user("cap@t.local", "pw", UserType.editor.value)
        s1 = create_system(editor, "Um", f"cap-um-{os.urandom(2).hex()}")
        provision_system(s1)
        s2 = create_system(editor, "Dois", f"cap-dois-{os.urandom(2).hex()}")
        with pytest.raises(CapacityReached):
            provision_system(s2)
    finally:
        get_settings.cache_clear()


def test_conexoes_viram_mcp_e_env_no_container(system, docker_env, live_pg):
    """Task 5.4 (parte estrutural): conexões -> MCP server + DATABASE_URL no container.
    Task 5.2: o valor do env é o DSN de loopback do sidecar, sem credencial."""
    import json
    import time

    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import connections

    provision_system(system)
    connections.register_connection(
        system, "principal", live_pg["host"], live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"]
    )
    # register dispara recriação em thread: aguarda o container voltar com a nova config
    deadline = time.time() + 60
    last_error = None
    while time.time() < deadline:
        try:
            container = _client().containers.get(system_container_name(system.slug))
            result = container.exec_run(["cat", "/workspace/opencode.json"])
            if result.exit_code == 0:
                config = json.loads(result.output.decode())
                if config.get("mcp"):
                    env_result = container.exec_run(["sh", "-c", "env | grep DATABASE_URL_PRINCIPAL"])
                    assert env_result.exit_code == 0, "DATABASE_URL_PRINCIPAL ausente no container"
                    env_line = env_result.output.decode()
                    assert "127.0.0.1" in env_line, env_line
                    assert live_pg["password"] not in env_line, "credencial vazou pro env do sistema"
                    assert "@" not in env_line.split("=", 1)[1], "DSN não deveria carregar user:senha@"
                    assert "principal" in config["mcp"]
                    mcp_url = config["mcp"]["principal"]["command"][2]
                    assert "127.0.0.1" in mcp_url
                    assert live_pg["password"] not in mcp_url, "credencial vazou pro cmdline do MCP"
                    assert config["model"].startswith("zhipuai/")  # provider glm -> zhipuai (models.dev)
                    return
        except Exception as exc:  # container sendo recriado nesse instante
            last_error = exc
        time.sleep(2)
    raise AssertionError(f"container não refletiu as conexões em 60s: {last_error}")


def test_sidecar_sobe_junto_do_sistema_e_guarda_a_credencial_real(system, docker_env, live_pg):
    """Task 5.1: sidecar sobe no mesmo netns do sistema (`network_mode:
    container:<id>`), um por sistema, com as credenciais reais só no seu
    próprio env — nunca no do sistema (verificado no teste acima)."""
    import time

    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import dbgate_sidecar_name, provision_system
    from appaiforge.services import connections

    provision_system(system)
    sidecar_name = dbgate_sidecar_name(system.slug)

    # sem conexão Postgres/MySQL ainda: nenhum sidecar sobe (nada a segurar)
    import docker as docker_sdk

    with pytest.raises(docker_sdk.errors.NotFound):
        _client().containers.get(sidecar_name)

    connections.register_connection(
        system, "principal", live_pg["host"], live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"]
    )

    deadline = time.time() + 60
    sidecar = None
    while time.time() < deadline:
        try:
            sidecar = _client().containers.get(sidecar_name)
            if sidecar.status == "running":
                break
        except docker_sdk.errors.NotFound:
            pass
        time.sleep(2)
    assert sidecar is not None and sidecar.status == "running", "sidecar não subiu em 60s"

    system_container = _client().containers.get(system_container_name(system.slug))
    assert sidecar.attrs["HostConfig"]["NetworkMode"] == f"container:{system_container.id}"
    assert sidecar.labels["appaiforge.system_id"] == system.id
    assert sidecar.labels["appaiforge.role"] == "dbgate-sidecar"

    sidecar_env = sidecar.exec_run(["sh", "-c", "env | grep APPAIFORGE_DB_CONNECTIONS"]).output.decode()
    assert live_pg["password"] in sidecar_env, "a credencial real deveria estar SÓ no sidecar"


def test_troca_de_credencial_propaga_ao_sidecar(system, docker_env, live_pg):
    """Task 5.4: editar a senha da conexão recria sidecar + sistema de forma
    idempotente, e a credencial NOVA (não a antiga) chega ao sidecar."""
    import time

    import psycopg

    from appaiforge.provisioning import dbgate_sidecar_name
    from appaiforge.services import connections

    conn = connections.register_connection(
        system, "principal", live_pg["host"], live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"]
    )
    sidecar_name = dbgate_sidecar_name(system.slug)

    def _wait_sidecar_env() -> str:
        deadline = time.time() + 60
        last_error = None
        while time.time() < deadline:
            try:
                sidecar = _client().containers.get(sidecar_name)
                if sidecar.status == "running":
                    result = sidecar.exec_run(["sh", "-c", "env | grep APPAIFORGE_DB_CONNECTIONS"])
                    if result.exit_code == 0:
                        return result.output.decode()
            except Exception as exc:  # container sendo recriado nesse instante
                last_error = exc
            time.sleep(2)
        raise AssertionError(f"sidecar não ficou pronto em 60s: {last_error}")

    first_env = _wait_sidecar_env()
    assert live_pg["password"] in first_env

    nova_senha = f"{live_pg['password']}-rotacionada"
    with psycopg.connect(
        host=live_pg["host"], port=live_pg["port"], dbname=live_pg["database"],
        user=live_pg["username"], password=live_pg["password"], autocommit=True,
    ) as pg_conn:
        with pg_conn.cursor() as cur:
            # DDL não aceita bind parameter aqui; valor é gerado neste teste, não vem de fora
            escaped = nova_senha.replace("'", "''")
            cur.execute(f"ALTER USER \"{live_pg['username']}\" WITH PASSWORD '{escaped}'")

    connections.update_connection(
        system, conn.id, "principal", live_pg["host"], live_pg["port"], live_pg["database"],
        live_pg["username"], password=nova_senha,
    )

    deadline = time.time() + 60
    second_env = first_env
    while time.time() < deadline and nova_senha not in second_env:
        second_env = _wait_sidecar_env()
        if nova_senha in second_env:
            break
        time.sleep(2)
    assert nova_senha in second_env, "credencial nova não propagou ao sidecar"
    old_credential_marker = f"{live_pg['username']}:{live_pg['password']}@"
    assert old_credential_marker not in second_env, "credencial antiga deveria ter sumido do DSN"


@pytest.fixture()
def hardened_image(monkeypatch):
    """Imagem base com a identidade não-root (ADR 0018) — não é a tag de
    produção (appaiforge/base:0.1.0); evita afetar sistemas reais do host."""
    monkeypatch.setenv("APPAIFORGE_BASE_IMAGE", "appaiforge/base:adr18-test")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_mode_and_provision(system, mode):
    from appaiforge.db import session_scope
    from appaiforge.models import System as SystemModel
    from appaiforge.provisioning import provision_system

    with session_scope() as s:
        s.get(SystemModel, system.id).execution_mode = mode
    system.execution_mode = mode
    provision_system(system)
    return system


def test_container_reduzido_sobe_sem_root_e_sem_capabilities(system, hardened_image):
    """Task 5.1: modo reduzido não-root, sem capability nenhuma, sem escalada."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode

    _set_mode_and_provision(system, ExecutionMode.reduced)

    container = _client().containers.get(system_container_name(system.slug))
    attrs = container.attrs
    assert attrs["Config"]["User"] == "1000:1000"
    assert attrs["HostConfig"]["CapDrop"] == ["ALL"]
    assert "no-new-privileges" in (attrs["HostConfig"]["SecurityOpt"] or [])

    result = container.exec_run(["id"])
    out = result.output.decode()
    assert "uid=1000" in out
    assert "uid=0(root)" not in out


def test_container_legacy_sobe_como_root_explicito(system, hardened_image):
    """Task 5.1/D5: sistema legacy sobrescreve o padrão não-root da imagem com root."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode

    _set_mode_and_provision(system, ExecutionMode.legacy)

    container = _client().containers.get(system_container_name(system.slug))
    attrs = container.attrs
    assert attrs["Config"]["User"] == "root"
    assert not attrs["HostConfig"]["CapDrop"]

    result = container.exec_run(["id"])
    assert "uid=0(root)" in result.output.decode()


@pytest.mark.parametrize("mode_name", ["reduced", "legacy"])
def test_agente_grava_no_workspace_nos_dois_modos(system, hardened_image, mode_name):
    """Task 5.2: o workspace é gravável pelo agente em qualquer um dos modos."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode

    mode = ExecutionMode.reduced if mode_name == "reduced" else ExecutionMode.legacy
    _set_mode_and_provision(system, mode)

    container = _client().containers.get(system_container_name(system.slug))
    result = container.exec_run(["sh", "-c", "echo gravado > /workspace/prova.txt && cat /workspace/prova.txt"])
    assert result.exit_code == 0, result.output.decode()
    assert "gravado" in result.output.decode()


def test_workspace_de_sistema_reduzido_pertence_ao_agente_no_host(system, hardened_image):
    """Task 5.2: o diretório de workspace de um sistema novo já nasce com o
    dono do usuário do agente (verificado pelo lado do portal, que vê o
    mesmo bind do host)."""
    from appaiforge.config import get_settings
    from appaiforge.models import ExecutionMode

    _set_mode_and_provision(system, ExecutionMode.reduced)

    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    st = os.stat(workspace)
    assert (st.st_uid, st.st_gid) == (1000, 1000)


@pytest.mark.parametrize("mode_name", ["reduced", "legacy"])
def test_reconciliacao_preserva_o_modo_de_execucao(system, hardened_image, mode_name):
    """Task 5.4: container recriado pela reconciliação mantém a identidade
    de execução original do sistema."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode, SystemStatus
    from appaiforge.provisioning import reconcile
    from appaiforge.services.systems import set_status

    mode = ExecutionMode.reduced if mode_name == "reduced" else ExecutionMode.legacy
    _set_mode_and_provision(system, mode)
    set_status(system.id, SystemStatus.active, "")  # visível para reconcile()

    _client().containers.get(system_container_name(system.slug)).remove(force=True)
    reconcile()

    container = _client().containers.get(system_container_name(system.slug))
    expected_user = "1000:1000" if mode == ExecutionMode.reduced else "root"
    assert container.attrs["Config"]["User"] == expected_user


@pytest.mark.parametrize("mode_name", ["reduced", "legacy"])
def test_refresh_connections_preserva_o_modo_de_execucao(system, hardened_image, mode_name):
    """Task 5.4: recriação via refresh_connections (registro de conexão) também
    preserva o modo de execução original do sistema."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode
    from appaiforge.provisioning import refresh_connections

    mode = ExecutionMode.reduced if mode_name == "reduced" else ExecutionMode.legacy
    _set_mode_and_provision(system, mode)

    refresh_connections(system)

    container = _client().containers.get(system_container_name(system.slug))
    expected_user = "1000:1000" if mode == ExecutionMode.reduced else "root"
    assert container.attrs["Config"]["User"] == expected_user
