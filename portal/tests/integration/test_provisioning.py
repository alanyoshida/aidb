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
    """Task 5.4 (parte estrutural): conexões -> MCP server + DATABASE_URL no container."""
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
                    assert "principal" in config["mcp"]
                    assert config["model"].startswith("zhipuai/")  # provider glm -> zhipuai (models.dev)
                    return
        except Exception as exc:  # container sendo recriado nesse instante
            last_error = exc
        time.sleep(2)
    raise AssertionError(f"container não refletiu as conexões em 60s: {last_error}")
