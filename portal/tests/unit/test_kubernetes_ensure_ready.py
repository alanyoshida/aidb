"""ensure_ready do driver Kubernetes: cria o namespace dos sistemas se faltar, e segue sem
erro quando o ServiceAccount não pode lê-lo (chart com rbac.clusterScoped=false)."""

import pytest
from kubernetes.client.exceptions import ApiException

from appaiforge.drivers import kubernetes_driver


class _Api:
    def __init__(self, status: int | None):
        self.status = status
        self.created: list[str] = []

    def read_namespace(self, name):
        if self.status is not None:
            raise ApiException(status=self.status)

    def create_namespace(self, body):
        self.created.append(body.metadata.name)


def _ensure(monkeypatch, status):
    api = _Api(status)
    monkeypatch.setattr(kubernetes_driver, "_api", lambda: api)
    kubernetes_driver.KubernetesProvisioningDriver().ensure_ready()
    return api


def test_namespace_existente_nao_e_criado(monkeypatch):
    assert _ensure(monkeypatch, None).created == []


def test_namespace_ausente_e_criado(monkeypatch):
    assert len(_ensure(monkeypatch, 404).created) == 1


def test_sem_permissao_de_leitura_segue_sem_criar(monkeypatch):
    assert _ensure(monkeypatch, 403).created == []


def test_outro_erro_propaga(monkeypatch):
    with pytest.raises(ApiException):
        _ensure(monkeypatch, 500)
