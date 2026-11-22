"""Rotas de /apps/<slug> no driver Kubernetes nos dois modos de roteamento (change
gateway-api-traefik-subchart): construtores de objetos, substituição sem apagar (D5), limpeza
dos objetos do outro modo (D6) e validação do modo (D0). Sem cluster: CoreV1Api e
CustomObjectsApi falsos, gravando as chamadas."""

from types import SimpleNamespace

import pytest
from kubernetes.client.exceptions import ApiException

from appaiforge.config import get_settings
from appaiforge.drivers import kubernetes_driver as kd
from appaiforge.edge import system_container_name

TRAEFIK = ("traefik.io", "v1alpha1")
GATEWAY = ("gateway.networking.k8s.io", "v1")


@pytest.fixture
def settings(monkeypatch):
    """Aplica variáveis APPAIFORGE_* e limpa o cache de settings antes e depois."""

    def apply(**env):
        for key, value in env.items():
            monkeypatch.setenv(f"APPAIFORGE_{key}", value)
        get_settings.cache_clear()
        return get_settings()

    get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


GATEWAY_ENV = {"K8S_ROUTING_MODE": "gateway", "K8S_GATEWAY_NAME": "aidb", "K8S_GATEWAY_NAMESPACE": "infra"}


class _Custom:
    """CustomObjectsApi falso: guarda objetos por (grupo, plural, nome) e grava as chamadas."""

    def __init__(self, existing: dict | None = None):
        self.objects = dict(existing or {})
        self.calls: list[tuple] = []

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        self.calls.append(("get", group, plural, name))
        if (group, plural, name) not in self.objects:
            raise ApiException(status=404)
        return self.objects[(group, plural, name)]

    def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        self.calls.append(("create", group, plural, body["metadata"]["name"]))
        self.objects[(group, plural, body["metadata"]["name"])] = body

    def replace_namespaced_custom_object(self, group, version, namespace, plural, name, body):
        self.calls.append(("replace", group, plural, name, body["metadata"].get("resourceVersion")))
        self.objects[(group, plural, name)] = body

    def delete_namespaced_custom_object(self, group, version, namespace, plural, name):
        self.calls.append(("delete", group, plural, name))
        if self.objects.pop((group, plural, name), None) is None:
            raise ApiException(status=404)


class _Core:
    def replace_namespaced_service(self, name, namespace, body):
        pass

    def delete_namespaced_service(self, name, namespace):
        raise ApiException(status=404)


def _route_kinds(custom: _Custom) -> set[tuple[str, str]]:
    return {(plural, name) for (_, plural, name) in custom.objects}


def _wire(monkeypatch, custom: _Custom):
    monkeypatch.setattr(kd, "_api", lambda: _Core())
    monkeypatch.setattr(kd, "_custom_api", lambda: custom)


SYSTEM = SimpleNamespace(slug="erp", agent_profile="opencode")
NAME = system_container_name("erp")


# --- configuração e validação do modo (D0) ---------------------------------------------------

def test_padrao_e_ingressroute_sem_gateway(settings):
    s = settings()
    assert s.k8s_routing_mode == "ingressroute"
    assert (s.k8s_gateway_name, s.k8s_gateway_namespace, s.k8s_route_hostname) == ("", "", "")
    assert kd._routing_mode(s) == "ingressroute"


def test_configuracao_lida_do_ambiente(settings):
    s = settings(**GATEWAY_ENV, K8S_ROUTE_HOSTNAME="aidb.exemplo.com")
    assert (s.k8s_routing_mode, s.k8s_gateway_name, s.k8s_gateway_namespace, s.k8s_route_hostname) == (
        "gateway", "aidb", "infra", "aidb.exemplo.com")
    assert kd._routing_mode(s) == "gateway"


def test_modo_desconhecido_nomeia_os_aceitos(settings):
    with pytest.raises(kd.UnknownRoutingMode, match="ingressroute ou gateway"):
        kd._routing_mode(settings(K8S_ROUTING_MODE="ingress"))


def test_modo_gateway_sem_gateway_configurado(settings):
    with pytest.raises(kd.UnknownRoutingMode, match="APPAIFORGE_K8S_GATEWAY_NAME"):
        kd._routing_mode(settings(K8S_ROUTING_MODE="gateway"))


def test_ensure_ready_recusa_modo_desconhecido(settings, monkeypatch):
    settings(K8S_ROUTING_MODE="nao-existe")
    monkeypatch.setattr(kd, "_api", lambda: pytest.fail("não deveria chegar à API"))
    with pytest.raises(kd.UnknownRoutingMode):
        kd.KubernetesProvisioningDriver().ensure_ready()


# --- construtores de objetos -----------------------------------------------------------------

def test_modo_ingressroute_gera_os_objetos_de_antes():
    objs = kd.app_route_objects("ns", NAME, "erp", 8080)
    assert [(plural, o["kind"], o["metadata"]["name"]) for plural, o in objs] == [
        ("middlewares", "Middleware", f"{NAME}-auth"),
        ("middlewares", "Middleware", f"{NAME}-strip"),
        ("ingressroutes", "IngressRoute", NAME),
    ]
    route = objs[2][1]["spec"]
    assert route == {
        "entryPoints": ["web"],
        "routes": [{
            "match": "PathPrefix(`/apps/erp`)", "kind": "Rule", "priority": 100,
            "middlewares": [{"name": f"{NAME}-auth"}, {"name": f"{NAME}-strip"}],
            "services": [{"name": NAME, "port": 8080}],
        }],
    }
    assert objs[1][1]["spec"] == {"stripPrefix": {"prefixes": ["/apps/erp"]}}


def test_modo_gateway_gera_auth_e_httproute_com_filtros_em_ordem():
    objs = kd.gateway_route_objects("ns", NAME, "erp", 8080, gateway_name="aidb", gateway_namespace="infra")
    (p_auth, auth), (p_route, route) = objs
    assert (p_auth, auth) == ("middlewares", kd.app_route_objects("ns", NAME, "erp", 8080)[0][1])
    assert p_route == "httproutes" and route["apiVersion"] == "gateway.networking.k8s.io/v1"
    spec = route["spec"]
    assert spec["parentRefs"] == [{"name": "aidb", "namespace": "infra"}]
    assert "hostnames" not in spec
    (rule,) = spec["rules"]
    assert rule["matches"] == [{"path": {"type": "PathPrefix", "value": "/apps/erp"}}]
    # forwardAuth antes da reescrita: o portal precisa ver o caminho original (spike S1)
    assert [f["type"] for f in rule["filters"]] == ["ExtensionRef", "URLRewrite"]
    assert rule["filters"][0]["extensionRef"] == {"group": "traefik.io", "kind": "Middleware", "name": f"{NAME}-auth"}
    assert rule["filters"][1]["urlRewrite"] == {"path": {"type": "ReplacePrefixMatch", "replacePrefixMatch": "/"}}
    assert rule["backendRefs"] == [{"name": NAME, "port": 8080}]


def test_modo_gateway_com_hostname_da_rota_do_portal():
    _, (_, route) = kd.gateway_route_objects("ns", NAME, "erp", 8080, gateway_name="aidb",
                                             gateway_namespace="infra", hostname="aidb.exemplo.com")
    assert route["spec"]["hostnames"] == ["aidb.exemplo.com"]


# --- substituição sem apagar (D5) ------------------------------------------------------------

def test_upsert_cria_quando_nao_existe():
    custom = _Custom()
    body = kd.app_route_objects("ns", NAME, "erp", 8080)[2][1]
    kd._upsert_custom(custom, "ns", "ingressroutes", NAME, body)
    assert [c[0] for c in custom.calls] == ["get", "create"]


def test_upsert_substitui_com_resource_version_sem_apagar():
    _, route = kd.gateway_route_objects("ns", NAME, "erp", 8080, gateway_name="g", gateway_namespace="n")[1]
    custom = _Custom({(GATEWAY[0], "httproutes", NAME): {"metadata": {"name": NAME, "resourceVersion": "42"}}})
    kd._upsert_custom(custom, "ns", "httproutes", NAME, route)
    assert custom.calls == [("get", GATEWAY[0], "httproutes", NAME), ("replace", GATEWAY[0], "httproutes", NAME, "42")]
    assert "resourceVersion" not in route["metadata"]  # o corpo original não é alterado


# --- publish / unpublish nos dois modos (D6) -------------------------------------------------

def _old_ingressroute_objects() -> dict:
    return {(TRAEFIK[0], plural, o["metadata"]["name"]): {**o, "metadata": {**o["metadata"], "resourceVersion": "1"}}
            for plural, o in kd.app_route_objects("ns", NAME, "erp", 8080)}


def test_publish_modo_ingressroute_apaga_o_httproute(settings, monkeypatch):
    settings()
    custom = _Custom({(GATEWAY[0], "httproutes", NAME): {"metadata": {"name": NAME, "resourceVersion": "9"}}})
    _wire(monkeypatch, custom)
    kd.KubernetesProvisioningDriver().publish(SYSTEM)
    assert _route_kinds(custom) == {("middlewares", f"{NAME}-auth"), ("middlewares", f"{NAME}-strip"),
                                    ("ingressroutes", NAME)}
    assert not [c for c in custom.calls if c[0] == "delete" and c[1] == TRAEFIK[0]]


def test_publish_modo_gateway_migra_da_forma_antiga(settings, monkeypatch):
    settings(**GATEWAY_ENV, K8S_ROUTE_HOSTNAME="aidb.exemplo.com")
    custom = _Custom(_old_ingressroute_objects())
    _wire(monkeypatch, custom)
    kd.KubernetesProvisioningDriver().publish(SYSTEM)
    assert _route_kinds(custom) == {("middlewares", f"{NAME}-auth"), ("httproutes", NAME)}
    route = custom.objects[(GATEWAY[0], "httproutes", NAME)]
    assert route["spec"]["parentRefs"] == [{"name": "aidb", "namespace": "infra"}]
    assert route["spec"]["hostnames"] == ["aidb.exemplo.com"]
    # o auth, comum aos dois modos, é substituído no lugar, nunca apagado
    assert ("replace", TRAEFIK[0], "middlewares", f"{NAME}-auth", "1") in custom.calls
    assert ("delete", TRAEFIK[0], "middlewares", f"{NAME}-auth") not in custom.calls


def test_publish_sem_objetos_do_outro_modo_nao_falha(settings, monkeypatch):
    settings(**GATEWAY_ENV)
    custom = _Custom()
    _wire(monkeypatch, custom)
    kd.KubernetesProvisioningDriver().publish(SYSTEM)  # deletes do outro modo dão 404 e seguem
    assert _route_kinds(custom) == {("middlewares", f"{NAME}-auth"), ("httproutes", NAME)}


@pytest.mark.parametrize("env", [{}, GATEWAY_ENV])
def test_unpublish_apaga_os_objetos_dos_dois_modos(settings, monkeypatch, env):
    settings(**env)
    custom = _Custom(_old_ingressroute_objects())  # só a forma do modo ingressroute existe
    _wire(monkeypatch, custom)
    kd.KubernetesProvisioningDriver().unpublish("erp")
    assert custom.objects == {}
    deleted = {(c[1], c[2], c[3]) for c in custom.calls if c[0] == "delete"}
    assert (GATEWAY[0], "httproutes", NAME) in deleted  # tentado, 404 tolerado


def test_delete_propaga_erro_que_nao_e_404():
    class _Forbidden(_Custom):
        def delete_namespaced_custom_object(self, *a):
            raise ApiException(status=403)

    with pytest.raises(ApiException):
        kd._delete_custom(_Forbidden(), "ns", *GATEWAY, "httproutes", NAME)
