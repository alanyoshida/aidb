"""Unitários da seleção de driver de provisionamento (change `add-kubernetes-driver`, task 1.3).

`get_driver()` resolve a implementação a partir de `settings.provisioning_driver`; estes testes
confirmam a fábrica em si e que cada ponto de `provisioning.py` que antes falava direto com o SDK
do Docker agora passa pelo driver resolvido, sem reimplementar os testes Docker-específicos já
existentes (`test_llm_provisioning.py`, `test_https_proxy_allowlist.py` etc.)."""

import pytest

from appaiforge import auth
from appaiforge.config import get_settings
from appaiforge.drivers import UnknownDriver, get_driver
from appaiforge.drivers.docker_driver import DockerProvisioningDriver
from appaiforge.models import UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("driver@t.local", "pw", UserType.editor.value)


def test_get_driver_default_e_docker():
    assert isinstance(get_driver(), DockerProvisioningDriver)


def test_get_driver_le_a_configuracao(monkeypatch):
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "docker")
    get_settings.cache_clear()
    try:
        assert isinstance(get_driver(), DockerProvisioningDriver)
    finally:
        get_settings.cache_clear()


def test_get_driver_desconhecido_levanta_unknown_driver(monkeypatch):
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "nao-existe")
    get_settings.cache_clear()
    try:
        with pytest.raises(UnknownDriver):
            get_driver()
    finally:
        get_settings.cache_clear()


class _FakeDriver:
    """Grava cada método chamado, sem tocar Docker nem nenhum backend real —
    confirma só a fiação entre `provisioning.py` e o driver resolvido."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def ensure_ready(self):
        self.calls.append(("ensure_ready", ()))

    def provision(self, system, *, env, manifest):
        self.calls.append(("provision", (system.id,)))
        return "fake-unit-id"

    def remove(self, system):
        self.calls.append(("remove", (system.id,)))

    def reconcile_one(self, system_id, slug):
        self.calls.append(("reconcile_one", (system_id, slug)))

    def refresh_https_allowlist(self, system):
        self.calls.append(("refresh_https_allowlist", (system.id,)))

    def healthcheck_url(self, system):
        self.calls.append(("healthcheck_url", (system.id,)))
        return "http://fake/"


@pytest.fixture()
def fake_driver(monkeypatch):
    driver = _FakeDriver()
    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: driver)
    return driver


def test_ensure_network_usa_o_driver_resolvido(fake_driver):
    from appaiforge.provisioning import ensure_network

    ensure_network()
    assert fake_driver.calls == [("ensure_ready", ())]


def test_provision_system_usa_o_driver_resolvido(editor, fake_driver, monkeypatch):
    system = create_system(editor, "Driver", "driver-provision")
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setattr("appaiforge.provisioning.write_opencode_config", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.provisioning.write_agent_profile", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.provisioning._provider_env", lambda *a: {})
    monkeypatch.setattr("appaiforge.provisioning._connection_env", lambda *a: {})

    from appaiforge.provisioning import provision_system

    container_id = provision_system(system)

    assert container_id == "fake-unit-id"
    assert ("ensure_ready", ()) in fake_driver.calls
    assert ("provision", (system.id,)) in fake_driver.calls


def test_stop_and_remove_usa_o_driver_resolvido(editor, fake_driver):
    system = create_system(editor, "Driver", "driver-remove")
    from appaiforge.provisioning import stop_and_remove

    stop_and_remove(system)
    assert fake_driver.calls == [("remove", (system.id,))]


def test_healthcheck_url_usa_o_driver_resolvido(editor, fake_driver):
    system = create_system(editor, "Driver", "driver-health")
    from appaiforge.provisioning import healthcheck_url

    url = healthcheck_url(system)
    assert url == "http://fake/"
    assert fake_driver.calls == [("healthcheck_url", (system.id,))]


def test_refresh_https_allowlist_usa_o_driver_resolvido(editor, fake_driver):
    system = create_system(editor, "Driver", "driver-allowlist")
    system.container_id = "already-provisioned"
    from appaiforge.provisioning import refresh_https_allowlist

    refresh_https_allowlist(system)
    assert fake_driver.calls == [("refresh_https_allowlist", (system.id,))]


def test_refresh_https_allowlist_sem_container_nao_chama_driver(editor, fake_driver):
    system = create_system(editor, "Driver", "driver-allowlist-vazio")
    from appaiforge.provisioning import refresh_https_allowlist

    refresh_https_allowlist(system)
    assert fake_driver.calls == []


def test_reconcile_usa_reconcile_one_do_driver_resolvido(editor, fake_driver, monkeypatch):
    system = create_system(editor, "Driver", "driver-reconcile")
    from appaiforge.services.systems import set_status
    from appaiforge.models import SystemStatus

    set_status(system.id, SystemStatus.active, "")
    monkeypatch.setattr("appaiforge.provisioning.publish_app_by_slug", lambda *a: None)
    monkeypatch.setattr("appaiforge.provisioning._check_connections_health", lambda *a: None)

    from appaiforge.provisioning import reconcile

    reconcile()
    assert ("reconcile_one", (system.id, system.slug)) in fake_driver.calls
