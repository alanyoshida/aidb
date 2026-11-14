"""Fallback de autenticação do driver Kubernetes (change `deploy-portal-in-cluster`).

`_load_kube_config()` tenta a identidade do próprio Pod (`ServiceAccount`, quando o portal roda
dentro do cluster) antes do kubeconfig com contexto explícito (fluxo de fora do cluster, já
validado na etapa anterior). Mocka as duas chamadas do SDK — não precisa de cluster real nem de
`ServiceAccount` montado."""

from appaiforge.config import get_settings
from appaiforge.drivers import kubernetes_driver as kd


def test_usa_incluster_quando_disponivel(monkeypatch):
    calls = []
    monkeypatch.setattr(kd.k8s_config, "load_incluster_config", lambda: calls.append("incluster"))
    monkeypatch.setattr(kd.k8s_config, "load_kube_config", lambda **kw: calls.append(("kubeconfig", kw)))
    kd._auth_mode_logged = False

    kd._load_kube_config()

    assert calls == ["incluster"]


def test_cai_pro_kubeconfig_quando_incluster_indisponivel(monkeypatch):
    def _sem_service_account():
        raise kd.k8s_config.ConfigException("sem ServiceAccount montado")

    calls = []
    monkeypatch.setattr(kd.k8s_config, "load_incluster_config", _sem_service_account)
    monkeypatch.setattr(kd.k8s_config, "load_kube_config", lambda **kw: calls.append(("kubeconfig", kw)))
    monkeypatch.setenv("APPAIFORGE_K8S_KUBECONFIG_CONTEXT", "kind-contexto-de-teste")
    get_settings.cache_clear()
    kd._auth_mode_logged = False

    try:
        kd._load_kube_config()
    finally:
        get_settings.cache_clear()

    assert calls == [("kubeconfig", {"context": "kind-contexto-de-teste"})]
