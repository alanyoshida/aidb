"""A chave de implantação nunca chega ao container do sistema, e o agente confinado não alcança o
servidor git (change add-system-git-remote, tarefa 3.9; requirement "Chave privada fora do
container do sistema")."""

import json
import os
import subprocess

import pytest

pytestmark = [pytest.mark.integration]

DRIVERS = ["docker"]
try:
    from kubernetes import config as k8s_config

    k8s_config.load_kube_config(context="kind-appaiforge-dev")
    DRIVERS.append("kubernetes")
except Exception:
    pass

# Procura um trecho exclusivo da chave privada em tudo que um processo do container alcança.
_SEARCH = r"""
# O trecho chega em duas metades e só é montado aqui: assim nem a linha de comando nem o ambiente
# deste próprio processo contêm o trecho inteiro (sem falso positivo consigo mesmo).
needle="$1$2"
grep -rIl --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev -F "$needle" / 2>/dev/null | head -5 | sed 's/^/arquivo:/'
for p in /proc/[0-9]*; do
  { tr '\0' '\n' < "$p/environ"; } 2>/dev/null | grep -qF "$needle" && echo "ambiente:$p"
  { tr '\0' ' ' < "$p/cmdline"; } 2>/dev/null | grep -qF "$needle" && echo "processo:$p"
done
true
"""


def _needle(system_id: str) -> str:
    """Uma linha do corpo base64 da chave privada do sistema (exclusiva desta chave)."""
    from appaiforge.services import git_remote

    lines = git_remote.load_secrets(system_id).private_key.strip().splitlines()
    return max(lines[1:-1], key=len)


def _link_and_push(system, owner, git_ssh_server, write) -> None:
    from appaiforge import checkpoints, git_sync
    from appaiforge.services import git_remote

    write("app.txt", "v1\n")
    checkpoints.record_checkpoint(system, None, "v1", owner)
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    git_ssh_server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    git_sync.activate(system, owner)
    write("app.txt", "v2\n")
    checkpoints.record_checkpoint(system, None, "v2", owner)
    git_sync.push_now(system, owner)
    assert git_ssh_server.git("rev-parse", "homolog") == checkpoints._git(system, "rev-parse", "HEAD")


@pytest.mark.parametrize("driver", DRIVERS)
def test_chave_privada_nunca_aparece_no_container(driver, tmp_path, monkeypatch, clean_db, git_ssh_server):
    import test_driver_parity as parity

    parity._setup_env(driver, tmp_path, monkeypatch)
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path / "gitdirs"))
    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(tmp_path / "relays"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    from appaiforge import auth
    from appaiforge.edge import system_container_name
    from appaiforge.models import UserType
    from appaiforge.provisioning import delete_system, provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    catalog.ensure_presets()
    owner = auth.create_user(f"isol-key-{driver}@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "IsolKey", f"isolkey-{driver}-{os.urandom(3).hex()}")
    try:
        provision_system(system)
        if driver == "kubernetes":
            from appaiforge.drivers.kubernetes_driver import _wait_for_agent_container_started

            _wait_for_agent_container_started(system_container_name(system.slug), "appaiforge-test", timeout=120)
        _link_and_push(system, owner, git_ssh_server,
                       lambda name, content: parity._write_workspace_file(driver, system, name, content))
        needle = _needle(system.id)

        if driver == "kubernetes":
            containers = ("agent", "git")
            runs = [subprocess.run(
                ["kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test", "exec",
                 system_container_name(system.slug), "-c", c, "--", "sh", "-c", _SEARCH, "sh", needle[:20], needle[20:]],
                capture_output=True, text=True, timeout=180) for c in containers]
        else:
            import docker

            container = docker.from_env().containers.get(system_container_name(system.slug))
            out = container.exec_run(["sh", "-c", _SEARCH, "sh", needle[:20], needle[20:]], user="root")
            runs = [subprocess.CompletedProcess([], out.exit_code, out.output.decode(), "")]
        for r in runs:
            assert r.returncode == 0, r.stderr
            assert r.stdout.strip() == "", f"chave privada encontrada no container: {r.stdout}"
        if driver == "docker":
            # controle positivo: a mesma busca acha o trecho quando ele está lá
            container.exec_run(["sh", "-c", 'printf "%s%s" "$1" "$2" > /tmp/controle', "sh", needle[:20], needle[20:]])
            found = container.exec_run(["sh", "-c", _SEARCH, "sh", needle[:20], needle[20:]], user="root")
            assert "arquivo:/tmp/controle" in found.output.decode()
            container.exec_run(["rm", "-f", "/tmp/controle"])
        delete_system(system)
    finally:
        parity._cleanup(driver, system)


def test_agente_confinado_nao_alcanca_o_servidor_git(system, docker_env, git_ssh_server, monkeypatch):
    import docker

    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode
    from appaiforge.provisioning import ensure_network, provision_system

    assert system.execution_mode == ExecutionMode.sandboxed
    ensure_network()
    provision_system(system)
    client = docker.from_env()
    network = client.networks.get(get_settings().docker_network)
    network.connect(git_ssh_server.container)
    git_ssh_server.container.reload()
    server_ip = git_ssh_server.container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]
    container = client.containers.get(system_container_name(system.slug))
    profile = json.loads(container.exec_run(["cat", "/opencode-config/agent-profile.json"]).output.decode())
    assert 22 not in profile["connect_tcp_ports"]

    script = f"""
import sys, socket, json
confinado = sys.argv[1] == "sim"
if confinado:
    sys.path.insert(0, "/opt/afsupervisor")
    from afsupervisor import sandbox
    sandbox.apply_landlock_net(connect_tcp_ports={profile["connect_tcp_ports"]!r},
                               bind_tcp_ports={profile["bind_tcp_ports"]!r})
try:
    socket.create_connection(("{server_ip}", 22), timeout=5).close()
    print("conectou")
except PermissionError as exc:
    print("negado")
except Exception as exc:
    print(type(exc).__name__)
"""
    controle = container.exec_run(["python3", "-c", script, "nao"]).output.decode().strip().splitlines()[-1]
    confinado = container.exec_run(["python3", "-c", script, "sim"]).output.decode().strip().splitlines()[-1]
    assert controle == "conectou", "sem o confinamento o servidor é alcançável: o teste prova algo"
    assert confinado == "negado"
