"""Unitários da allow-list do proxy HTTP(S) de saída (change
agent-https-forward-proxy): resolução do host do provedor (task 3.1),
allow-list padrão por sistema (3.2/3.3), os dois controles por sistema
(4.1-4.3 — internet habilitada, modo restrito) e a integração com o
provisionamento sem Docker real (5.1/5.3)."""

import json

import pytest

from appaiforge import auth
from appaiforge.config import get_settings
from appaiforge.models import UserType
from appaiforge.provisioning import PACKAGE_REGISTRY_HOSTS, default_https_allowlist
from appaiforge.services import catalog, network_policy
from appaiforge.services.systems import create_system


@pytest.fixture()
def admin(clean_db):
    catalog.ensure_presets()
    return auth.create_user("https-proxy@adm.local", "pw", UserType.admin.value)


@pytest.fixture()
def editor(clean_db):
    catalog.ensure_presets()
    return auth.create_user("https-proxy-ed@t.local", "pw", UserType.editor.value)


# ---------- 3.1: resolução do host do provedor ----------

def test_provider_host_openrouter():
    assert catalog.provider_host({"id": "openrouter", "base_url": None}) == "openrouter.ai"


def test_provider_host_openai():
    assert catalog.provider_host({"id": "openai", "base_url": None}) == "api.openai.com"


def test_provider_host_anthropic():
    assert catalog.provider_host({"id": "anthropic", "base_url": None}) == "api.anthropic.com"


def test_provider_host_glm_sem_base_url_cai_no_settings(monkeypatch):
    from appaiforge.config import get_settings

    monkeypatch.setenv("APPAIFORGE_GLM_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
    get_settings.cache_clear()
    try:
        assert catalog.provider_host({"id": "glm", "base_url": None}) == "api.z.ai"
    finally:
        get_settings.cache_clear()


def test_provider_host_openai_compatible_usa_base_url():
    provider = {"id": "custom-1", "base_url": "https://meu-proxy.internal:8443/v1"}
    assert catalog.provider_host(provider) == "meu-proxy.internal"


# ---------- 3.2/3.3: allow-list padrão por sistema ----------

def test_allowlist_padrao_inclui_registros_de_pacote(editor):
    system = create_system(editor, "Sys", "allowlist-pkg", provider="openrouter")
    allow = default_https_allowlist(system)
    for host_port in PACKAGE_REGISTRY_HOSTS:
        assert host_port in allow


def test_allowlist_padrao_sem_broker_inclui_host_do_provedor(editor, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "false")
    get_settings.cache_clear()
    try:
        system = create_system(editor, "Sys", "allowlist-sem-broker", provider="openrouter")
        allow = default_https_allowlist(system)
        assert ("openrouter.ai", 443) in allow
    finally:
        get_settings.cache_clear()


def test_allowlist_padrao_com_broker_inclui_host_do_broker_nao_do_provedor(editor, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    get_settings.cache_clear()
    try:
        system = create_system(editor, "Sys", "allowlist-com-broker", provider="openrouter")
        allow = default_https_allowlist(system)
        assert ("openrouter.ai", 443) not in allow
        extra = [hp for hp in allow if hp not in PACKAGE_REGISTRY_HOSTS]
        assert len(extra) == 1  # só o host:porta do broker, não o do provedor
    finally:
        get_settings.cache_clear()


# ---------- 4.1/4.2: pré-população da lista do modo restrito ----------

def test_sistema_novo_ja_nasce_com_a_lista_pre_populada(editor):
    system = create_system(editor, "Sys", "preseed-create", provider="openrouter")
    domains = {d["domain"] for d in network_policy.list_allowed_domains(system.id)}
    assert domains == {h for h, _ in PACKAGE_REGISTRY_HOSTS}


def test_seed_e_idempotente_nao_duplica_nem_reseta_edicao_do_editor(editor):
    system = create_system(editor, "Sys", "preseed-idempotente", provider="openrouter")
    network_policy.remove_allowed_domain(
        system.id, network_policy.list_allowed_domains(system.id)[0]["id"]
    )
    network_policy.add_allowed_domain(system.id, "minha-api.exemplo.com")
    before = {d["domain"] for d in network_policy.list_allowed_domains(system.id)}

    network_policy.seed_default_domains_if_empty(system.id)  # chamar de novo não deve mexer

    after = {d["domain"] for d in network_policy.list_allowed_domains(system.id)}
    assert after == before
    assert "minha-api.exemplo.com" in after


def test_add_allowed_domain_e_idempotente():
    from appaiforge import auth
    from appaiforge.models import UserType

    editor = auth.create_user("https-proxy-add@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Sys", "add-idempotente", provider="openrouter")
    first = network_policy.add_allowed_domain(system.id, "exemplo.com")
    second = network_policy.add_allowed_domain(system.id, "EXEMPLO.com")  # mesmo domínio, outra caixa
    assert first is not None
    assert second is None
    assert [d["domain"] for d in network_policy.list_allowed_domains(system.id) if d["domain"] == "exemplo.com"]


# ---------- 4.3: allow-list final (internet habilitada x modo restrito) ----------

def test_allowlist_final_usa_a_padrao_por_default(editor):
    from appaiforge.services.systems import get_system

    system = create_system(editor, "Sys", "final-default", provider="openrouter")
    allow = network_policy.final_https_allowlist(get_system(system.id))
    assert ("openrouter.ai", 443) in allow


def test_internet_desabilitada_esvazia_tudo_mesmo_com_modo_restrito_ligado(editor):
    from appaiforge.services.systems import get_system

    system = create_system(editor, "Sys", "final-internet-off", provider="openrouter")
    network_policy.set_restricted_network(system.id, True)
    network_policy.set_internet_enabled(system.id, False)
    allow = network_policy.final_https_allowlist(get_system(system.id))
    assert allow == []


def test_modo_restrito_substitui_a_padrao_por_completo(editor):
    from appaiforge.services.systems import get_system

    system = create_system(editor, "Sys", "final-restrito", provider="openrouter")
    network_policy.set_restricted_network(system.id, True)
    allow = network_policy.final_https_allowlist(get_system(system.id))
    assert ("openrouter.ai", 443) not in allow  # provedor não entra, só a lista cadastrada
    assert set(allow) == {(h, 443) for h, _ in PACKAGE_REGISTRY_HOSTS}  # pré-populada


# ---------- 5.1/5.3: sidecar e env do container principal (sem Docker real) ----------

def _provision_with_fake_docker(system, tmp_path, monkeypatch) -> list[dict]:
    import docker

    class FakeContainer:
        id = "fake-id"

    calls: list[dict] = []

    class FakeContainers:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def run(self, **kwargs):
            calls.append(kwargs)
            return FakeContainer()

    class FakeNetworks:
        def get(self, name):
            raise docker.errors.NotFound("not found")

        def create(self, name, driver=None):
            pass

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    monkeypatch.setattr("appaiforge.provisioning._docker", lambda: FakeClient())
    monkeypatch.setattr("appaiforge.provisioning.set_container", lambda *a: None)
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "host-workspaces"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "host-configs"))
    get_settings.cache_clear()
    try:
        from appaiforge.provisioning import provision_system

        provision_system(system)
    finally:
        get_settings.cache_clear()
    return calls


def test_provision_system_sobe_sidecar_do_proxy_https(editor, tmp_path, monkeypatch):
    from appaiforge.provisioning import httpsproxy_sidecar_name

    system = create_system(editor, "Sys", "prov-httpsproxy", provider="openrouter")
    calls = _provision_with_fake_docker(system, tmp_path, monkeypatch)

    sidecar_call = next(c for c in calls if c.get("name") == httpsproxy_sidecar_name(system.slug))
    assert sidecar_call["command"] == ["python", "/opt/httpproxy/sidecar.py"]
    assert sidecar_call["network_mode"] == "container:fake-id"
    allow = json.loads(sidecar_call["environment"]["ALLOWED_HOSTS"])
    assert ["openrouter.ai", 443] in allow


def test_provision_system_injeta_http_proxy_env_no_container_principal(editor, tmp_path, monkeypatch):
    from appaiforge.provisioning import HTTPS_PROXY_PORT

    system = create_system(editor, "Sys", "prov-http-proxy-env", provider="openrouter")
    calls = _provision_with_fake_docker(system, tmp_path, monkeypatch)

    main_call = next(c for c in calls if "volumes" in c)
    env = main_call["environment"]
    assert env["HTTP_PROXY"] == f"http://127.0.0.1:{HTTPS_PROXY_PORT}"
    assert env["HTTPS_PROXY"] == f"http://127.0.0.1:{HTTPS_PROXY_PORT}"
