"""Checagem do host Docker no boot de produção (change add-production-portal-install, task 3.1)."""

import pytest

from appaiforge import installation
from appaiforge.config import get_settings
from appaiforge.installation import INSTALLATION_LABEL, SharedDockerHost, foreign_containers

ME, OTHER = "a" * 32, "b" * 32


def _c(name, **labels):
    return (name, {"appaiforge.managed": "true", **labels})


def test_decisao_separa_os_containers_alheios():
    containers = [
        _c("meu", **{INSTALLATION_LABEL: ME, "appaiforge.system_id": "s1"}),
        _c("alheio", **{INSTALLATION_LABEL: OTHER, "appaiforge.system_id": "s1"}),
        _c("antigo-meu", **{"appaiforge.system_id": "s2"}),
        _c("antigo-alheio", **{"appaiforge.system_id": "zz"}),
        ("nao-gerenciado", {"appaiforge.system_id": "zz"}),
    ]
    assert foreign_containers(containers, {"s1", "s2"}, ME) == ["alheio", "antigo-alheio"]


class _Listed:
    def __init__(self, name, labels):
        self.name, self.labels = name, labels


class _Client:
    def __init__(self, items):
        self.containers = self
        self._items = items

    def list(self, all, filters):
        assert filters == {"label": "appaiforge.managed=true"}
        return [_Listed(n, labels) for n, labels in self._items]


def _setup(monkeypatch, role, items, allow=False, driver="docker"):
    monkeypatch.setenv("APPAIFORGE_INSTALLATION_ROLE", role)
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", driver)
    monkeypatch.setenv("APPAIFORGE_ALLOW_SHARED_DOCKER_HOST", "true" if allow else "false")
    get_settings.cache_clear()
    monkeypatch.setattr("appaiforge.provisioning._docker", lambda: _Client(items))


def test_producao_recusa_host_com_container_de_outra_instalacao(clean_db, monkeypatch):
    _setup(monkeypatch, "production", [_c("appaiforge-sys-vendas", **{INSTALLATION_LABEL: OTHER})])
    with pytest.raises(SharedDockerHost, match="appaiforge-sys-vendas.*host Docker próprio"):
        installation.check_docker_host()


def test_excecao_so_avisa(clean_db, monkeypatch, caplog):
    _setup(monkeypatch, "production", [_c("appaiforge-sys-vendas", **{INSTALLATION_LABEL: OTHER})], allow=True)
    installation.check_docker_host()
    assert "compartilhado" in caplog.text


def test_desenvolvimento_nao_checa(clean_db, monkeypatch):
    _setup(monkeypatch, "development", [_c("appaiforge-sys-vendas", **{INSTALLATION_LABEL: OTHER})])
    installation.check_docker_host()


def test_kubernetes_nao_checa(clean_db, monkeypatch):
    _setup(monkeypatch, "production", [_c("x", **{INSTALLATION_LABEL: OTHER})], driver="kubernetes")
    installation.check_docker_host()


def test_host_so_com_containers_proprios_passa(clean_db, monkeypatch):
    _setup(monkeypatch, "production", [])
    mine = installation.installation_id()
    _setup(monkeypatch, "production", [_c("appaiforge-sys-meu", **{INSTALLATION_LABEL: mine})])
    installation.check_docker_host()


def test_mensagem_lista_no_maximo_dez(clean_db, monkeypatch):
    items = [_c(f"c{i:02d}", **{INSTALLATION_LABEL: OTHER}) for i in range(13)]
    _setup(monkeypatch, "production", items)
    with pytest.raises(SharedDockerHost, match="e mais 3") as exc:
        installation.check_docker_host()
    assert "c09" in str(exc.value) and "c10" not in str(exc.value)
