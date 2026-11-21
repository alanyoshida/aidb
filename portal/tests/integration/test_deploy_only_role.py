"""Portal de produção não provisiona sistema com agente (change add-deploy-only-system, tarefa 1.3)."""

import os

import pytest

pytestmark = [pytest.mark.integration]


def test_producao_recusa_provisionar_e_reconciliar_sistema_com_agente(docker_env, clean_db, monkeypatch):
    import docker

    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import SystemStatus, UserType
    from appaiforge.provisioning import provision_system, reconcile
    from appaiforge.services import catalog
    from appaiforge.services.systems import AgentNotAllowedHere, create_system, get_system, set_status
    from conftest import remove_system_containers

    catalog.ensure_presets()
    editor = auth.create_user("role@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Agente", f"role-{os.urandom(3).hex()}")  # desenvolvimento
    try:
        provision_system(system)
        set_status(system.id, SystemStatus.active, "")
        name = system_container_name(system.slug)
        assert docker.from_env().containers.get(name).status in ("running", "created")

        monkeypatch.setenv("APPAIFORGE_INSTALLATION_ROLE", "production")
        get_settings.cache_clear()
        with pytest.raises(AgentNotAllowedHere):
            provision_system(system)

        reconcile()
        refreshed = get_system(system.id)
        assert refreshed.status == SystemStatus.error and "produção" in refreshed.status_message
        with pytest.raises(docker.errors.NotFound):
            docker.from_env().containers.get(name)
    finally:
        remove_system_containers(system.slug)


_LLM_MARKERS = ("API_KEY", "AIDB_AGENT_PROFILE", "INFERENCE", "BROKER")


def _assert_sem_agente(env_lines: list[str], cmdlines: str) -> None:
    names = [line.split("=", 1)[0] for line in env_lines if "=" in line]
    assert "AIDB_SYSTEM_KIND=deploy_only" in env_lines
    assert not [n for n in names if any(m in n for m in _LLM_MARKERS)], names
    assert "opencode" not in cmdlines and "claude" not in cmdlines, cmdlines


def _cmdlines_script() -> list[str]:
    return ["sh", "-c", "for f in /proc/[0-9]*/cmdline; do tr '\\0' ' ' < $f; echo; done"]


def test_sistema_so_implantacao_sobe_sem_agente_no_docker(docker_env, clean_db):
    import time

    import docker

    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import UserType
    from appaiforge.provisioning import default_https_allowlist, httpsproxy_sidecar_name, provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system
    from conftest import remove_system_containers

    catalog.ensure_presets()
    editor = auth.create_user("deploy@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Prod", f"dep-{os.urandom(3).hex()}", kind=KIND_DEPLOY_ONLY)
    try:
        provision_system(system)
        container = docker.from_env().containers.get(system_container_name(system.slug))
        time.sleep(3)  # supervisor inicia
        env_lines = container.attrs["Config"]["Env"]
        cmdlines = container.exec_run(_cmdlines_script()).output.decode()
        _assert_sem_agente(env_lines, cmdlines)
        assert "afsupervisor" in cmdlines or "supervisor" in cmdlines
        # nenhuma config de agente escrita
        config_dir = os.path.join(get_settings().configs_dir, system.slug)
        assert not os.path.exists(os.path.join(config_dir, "agent-profile.json"))
        assert not os.path.exists(os.path.join(config_dir, "opencode.json"))
        # allow-list só com registros de pacote
        from appaiforge.provisioning import PACKAGE_REGISTRY_HOSTS

        assert default_https_allowlist(system) == list(PACKAGE_REGISTRY_HOSTS)
        assert docker.from_env().containers.get(httpsproxy_sidecar_name(system.slug))
    finally:
        remove_system_containers(system.slug)


def test_exec_in_app_no_docker_roda_como_a_app_com_o_proxy(docker_env, clean_db):
    from appaiforge import auth
    from appaiforge.drivers import get_driver
    from appaiforge.models import UserType
    from appaiforge.provisioning import provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system
    from conftest import remove_system_containers

    catalog.ensure_presets()
    editor = auth.create_user("exec@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Exec", f"exec-{os.urandom(3).hex()}", kind=KIND_DEPLOY_ONLY)
    try:
        provision_system(system)
        code, out, _ = get_driver().exec_in_app(system, ["sh", "-c", "id -u; echo $HTTPS_PROXY; echo $EXTRA"], env={"EXTRA": "ok"})
        uid, proxy, extra = out.split()
        assert code == 0 and uid == "1000" and proxy.startswith("http://127.0.0.1:") and extra == "ok"
        code, _, err = get_driver().exec_in_app(system, ["sh", "-c", "echo falhou >&2; exit 3"])
        assert code == 3 and "falhou" in err
        code, _, _ = get_driver().exec_in_app(system, ["sleep", "10"], timeout=1)
        assert code == 124
    finally:
        remove_system_containers(system.slug)
