"""Unitários: a reconciliação do driver Docker religa container de sistema presente e parado,
e os sidecars depois dele (change reconcile-restart-stopped-container, D1/D2/D4). Cliente Docker
falso — a ordem das chamadas é o que importa aqui; o comportamento de rede real está no teste de
integração."""

import docker
import pytest

from appaiforge.drivers import ComputeUnitOwnedElsewhere
from appaiforge.drivers.docker_driver import DockerProvisioningDriver
from appaiforge.edge import system_container_name
from appaiforge.provisioning import dbgate_sidecar_name, httpsproxy_sidecar_name

SYSTEM_ID = "sys-1"
SLUG = "parado"


class FakeContainer:
    def __init__(self, name: str, status: str, events: list[tuple[str, str]], system_id: str = SYSTEM_ID):
        self.name = name
        self.id = f"id-{name}"
        self.status = status
        self.labels = {"appaiforge.managed": "true", "appaiforge.system_id": system_id}
        self._events = events

    def start(self):
        self._events.append(("start", self.name))
        self.status = "running"

    def restart(self, **_kwargs):
        self._events.append(("restart", self.name))
        self.status = "running"


class FakeClient:
    def __init__(self, containers: dict[str, FakeContainer]):
        self._containers = containers
        self.containers = self

    def get(self, name):
        try:
            return self._containers[name]
        except KeyError:
            raise docker.errors.NotFound(name) from None


@pytest.fixture()
def env(clean_db, monkeypatch):
    """Monta o host falso: `env(main=..., dbgate=..., httpsproxy=...)` com o estado de cada
    container (`None` = ausente) e devolve a lista de eventos (`start`/`restart`, nome)."""
    monkeypatch.setattr("appaiforge.provisioning.db_connections_manifest", lambda _sid: [{"alias": "db"}])

    def build(main="running", dbgate="running", httpsproxy="running", main_owner=SYSTEM_ID):
        events: list[tuple[str, str]] = []
        containers = {}
        for name, status, owner in (
            (system_container_name(SLUG), main, main_owner),
            (dbgate_sidecar_name(SLUG), dbgate, SYSTEM_ID),
            (httpsproxy_sidecar_name(SLUG), httpsproxy, SYSTEM_ID),
        ):
            if status is not None:
                containers[name] = FakeContainer(name, status, events, owner)
        monkeypatch.setattr("appaiforge.provisioning._docker", lambda: FakeClient(containers))
        return events

    return build


def test_container_do_sistema_parado_e_religado_e_sidecars_reiniciados_depois(env):
    # o dbgate ficou rodando preso à rede antiga; o proxy parou junto com o sistema
    events = env(main="exited", dbgate="running", httpsproxy="exited")

    DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events == [
        ("start", system_container_name(SLUG)),
        ("restart", dbgate_sidecar_name(SLUG)),
        ("restart", httpsproxy_sidecar_name(SLUG)),
    ]


def test_container_criado_e_nunca_iniciado_tambem_e_religado(env):
    events = env(main="created")

    DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events[0] == ("start", system_container_name(SLUG))


def test_sistema_rodando_com_sidecar_parado_so_religa_o_sidecar(env):
    events = env(main="running", dbgate="running", httpsproxy="exited")

    DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events == [("start", httpsproxy_sidecar_name(SLUG))]


def test_tudo_rodando_nao_toca_em_nada(env):
    events = env()

    DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events == []


@pytest.mark.parametrize("status", ["restarting", "paused"])
def test_outros_estados_do_sistema_ficam_como_estao(env, status):
    events = env(main=status)

    DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events == []


def test_container_parado_de_outro_dono_nao_e_religado(env):
    events = env(main="exited", main_owner="outro-sistema")

    with pytest.raises(ComputeUnitOwnedElsewhere):
        DockerProvisioningDriver().reconcile_one(SYSTEM_ID, SLUG)

    assert events == []
