"""Unitários do catálogo de provedores de LLM (task 1.2)."""

import pytest

from appaiforge import auth
from appaiforge.models import UserType
from appaiforge.services import audit, catalog


@pytest.fixture()
def admin(clean_db):
    catalog.ensure_presets()
    return auth.create_user("cat@adm.local", "pw", UserType.admin.value)


def _ids() -> set[str]:
    return {p["id"] for p in catalog.list_providers()}


def test_presets_disponiveis(admin):
    providers = {p["id"]: p for p in catalog.list_providers()}
    assert {"glm", "anthropic", "openai", "openrouter"} <= set(providers)
    assert providers["openrouter"]["kind"] == "native"
    assert providers["openrouter"]["env_name"] == "OPENROUTER_API_KEY"
    assert all(p["is_preset"] for p in providers.values())


def test_ensure_presets_idempotente(admin):
    before = len(catalog.list_providers())
    catalog.ensure_presets()
    catalog.ensure_presets()
    assert len(catalog.list_providers()) == before


def test_cria_provedor_openai_compatible(admin):
    created = catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1", actor=admin)
    assert created["kind"] == "openai-compatible"
    assert created["base_url"] == "https://api.minha.ai/v1"
    assert created["env_name"] == "MINHA_IA_API_KEY"
    assert "minha-ia" in _ids()
    assert audit.list_global(action="provider.create")


def test_compatible_exige_base_url(admin):
    with pytest.raises(catalog.InvalidProvider):
        catalog.create_provider("sem-url", "Sem URL", "openai-compatible", None, actor=admin)


def test_id_invalido(admin):
    with pytest.raises(catalog.InvalidProvider):
        catalog.create_provider("id_com_underscore", "X", "openai-compatible", "https://x/v1", actor=admin)


def test_preset_nao_removivel(admin):
    with pytest.raises(catalog.PresetProtected):
        catalog.delete_provider("glm", actor=admin)


def test_remove_provedor_custom(admin):
    catalog.create_provider("temp-ia", "Temp", "openai-compatible", "https://t/v1", actor=admin)
    catalog.delete_provider("temp-ia", actor=admin)
    assert "temp-ia" not in _ids()
    assert audit.list_global(action="provider.remove")


def test_update_provedor(admin):
    catalog.create_provider("edit-ia", "Antes", "openai-compatible", "https://a/v1", actor=admin)
    catalog.update_provider("edit-ia", "Depois", "https://b/v1", models=["m1"], actor=admin)
    provider = catalog.get_provider("edit-ia")
    assert provider["label"] == "Depois" and provider["base_url"] == "https://b/v1" and provider["models"] == ["m1"]


def test_gestao_restrita_ao_admin(clean_db):
    catalog.ensure_presets()
    editor = auth.create_user("ed@cat.local", "pw", UserType.editor.value)
    with pytest.raises(PermissionError):
        catalog.create_provider("x-ia", "X", "openai-compatible", "https://x/v1", actor=editor)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


def test_discover_models_guarda_a_lista(admin, monkeypatch):
    catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1", actor=admin)
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _Resp(200, {"data": [{"id": "m1"}, {"id": "m2"}]})

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    models = catalog.discover_models("minha-ia", actor=admin)
    assert captured["url"] == "https://api.minha.ai/v1/models"
    assert models == ["m1", "m2"]
    assert catalog.get_provider("minha-ia")["models"] == ["m1", "m2"]


def test_discover_openrouter_usa_rota_publica(admin, monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _Resp(200, {"data": [{"id": "openai/gpt-4o"}]})

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    catalog.discover_models("openrouter", actor=admin)
    assert captured["url"] == "https://openrouter.ai/api/v1/models"


def test_discover_falha_http(admin, monkeypatch):
    catalog.create_provider("falha-ia", "F", "openai-compatible", "https://f/v1", actor=admin)
    monkeypatch.setattr(catalog.httpx, "get", lambda *a, **k: _Resp(500, {"data": []}))
    with pytest.raises(catalog.DiscoveryFailed):
        catalog.discover_models("falha-ia", actor=admin)


def test_discover_sem_modelos(admin, monkeypatch):
    catalog.create_provider("vazia-ia", "V", "openai-compatible", "https://v/v1", actor=admin)
    monkeypatch.setattr(catalog.httpx, "get", lambda *a, **k: _Resp(200, {"data": []}))
    with pytest.raises(catalog.DiscoveryFailed):
        catalog.discover_models("vazia-ia", actor=admin)