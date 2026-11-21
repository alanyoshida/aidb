"""Containers com dono sob o driver Docker (change add-production-portal-install, tarefas 2.1, 2.3 e
2.4). Um container "de outra instalação" é simulado com o mesmo nome e outro rótulo."""

import pytest

pytestmark = [pytest.mark.integration]

OTHER = "f" * 32


def _client():
    import docker

    return docker.from_env()


def _foreign(name: str, system_id: str = "outro-sistema", installation: str | None = OTHER):
    """Container parado-mas-vivo com o nome dado e rótulos de outro dono."""
    from appaiforge.config import get_settings

    labels = {"appaiforge.managed": "true", "appaiforge.system_id": system_id, "appaiforge.slug": "x"}
    if installation:
        labels["appaiforge.installation"] = installation
    return _client().containers.run(
        get_settings().base_image, ["sleep", "600"], name=name, labels=labels, detach=True,
        network=get_settings().docker_network,
    )


def test_containers_do_sistema_levam_o_rotulo_da_instalacao(system):
    from appaiforge.drivers import get_driver
    from appaiforge.edge import system_container_name
    from appaiforge.installation import installation_id
    from appaiforge.provisioning import dbgate_sidecar_name, httpsproxy_sidecar_name, provision_system

    container_id = provision_system(system)
    # o sidecar do gate só sobe com conexão: força com um manifesto mínimo
    get_driver()._provision_dbgate_sidecar(
        system, container_id, [{"name": "vendas", "kind": "postgres", "host": "127.0.0.1", "port": 5432}])
    me = installation_id()
    for name in (system_container_name(system.slug), httpsproxy_sidecar_name(system.slug),
                 dbgate_sidecar_name(system.slug)):
        labels = _client().containers.get(name).labels
        assert labels["appaiforge.installation"] == me, name
        assert labels["appaiforge.system_id"] == system.id, name


def test_nome_ocupado_por_outra_instalacao_nao_e_tocado(system):
    from appaiforge.drivers import ComputeUnitOwnedElsewhere
    from appaiforge.edge import system_container_name
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import provision_system, reconcile
    from appaiforge.services.systems import get_system, set_status

    name = system_container_name(system.slug)
    alheio = _foreign(name)
    try:
        with pytest.raises(ComputeUnitOwnedElsewhere, match="outra instalação"):
            provision_system(system)
        alheio.reload()
        assert alheio.status == "running"

        set_status(system.id, SystemStatus.active, "")
        reconcile()
        refreshed = get_system(system.id)
        assert refreshed.status == SystemStatus.error
        assert "outra instalação" in refreshed.status_message
        alheio.reload()
        assert alheio.status == "running" and alheio.labels["appaiforge.installation"] == OTHER
    finally:
        alheio.remove(force=True)


def test_remocao_mantem_container_de_outro_dono(system):
    from appaiforge.drivers import get_driver
    from appaiforge.edge import system_container_name

    alheio = _foreign(system_container_name(system.slug), installation=None)
    try:
        get_driver().remove(system)
        alheio.reload()
        assert alheio.status == "running"
    finally:
        alheio.remove(force=True)


def test_container_antigo_do_proprio_sistema_e_substituido_e_ganha_rotulo(system):
    from appaiforge.edge import system_container_name
    from appaiforge.installation import installation_id
    from appaiforge.provisioning import provision_system

    name = system_container_name(system.slug)
    antigo = _foreign(name, system_id=system.id, installation=None)
    provision_system(system)
    novo = _client().containers.get(name)
    assert novo.id != antigo.id
    assert novo.labels["appaiforge.installation"] == installation_id()


def test_portal_de_producao_nao_sobe_em_host_com_outra_instalacao(docker_env, clean_db):
    """Tarefa 3.2: o app de produção, subido num processo próprio, falha antes de reconciliar
    qualquer coisa; com a exceção ligada, só avisa. O nome começa com "aidb-" para entrar entre
    os dez listados."""
    import os
    import subprocess
    import sys

    name = f"aidb-teste-alheio-{os.urandom(3).hex()}"
    alheio = _foreign(name)
    env = {**os.environ, "APPAIFORGE_PROVISIONING_DRIVER": "docker", "APPAIFORGE_INSTALLATION_ROLE": "production",
           "APPAIFORGE_SEED_DEMO_ADMIN": "0", "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    probe = "from appaiforge.installation import check_docker_host; check_docker_host(); print('subiu')"
    try:
        boot = subprocess.run([sys.executable, "-c", "import appaiforge.main"], env=env,
                              capture_output=True, text=True, timeout=120)
        assert boot.returncode != 0
        assert "SharedDockerHost" in boot.stderr and name in boot.stderr and "host Docker próprio" in boot.stderr

        allowed = subprocess.run([sys.executable, "-c", probe], env={**env, "APPAIFORGE_ALLOW_SHARED_DOCKER_HOST": "true"},
                                 capture_output=True, text=True, timeout=120)
        assert allowed.returncode == 0, allowed.stderr
        assert "subiu" in allowed.stdout and "compartilhado" in allowed.stderr and name in allowed.stderr
    finally:
        alheio.remove(force=True)
