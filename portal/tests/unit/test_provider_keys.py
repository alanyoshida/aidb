"""Unitários da gestão de chaves de LLM (task 7.1)."""

import pytest

from appaiforge import auth
from appaiforge.models import UserType
from appaiforge.services import audit, catalog, provider_keys


@pytest.fixture()
def admin(clean_db):
    catalog.ensure_presets()
    return auth.create_user("keys@adm.local", "pw", UserType.admin.value)


def test_set_e_remove_chave(admin):
    provider_keys.set_key("glm", "chave-secreta", actor=admin)
    state = {k["provider"]: k["configured"] for k in provider_keys.list_keys()}
    assert state["glm"] is True and state["anthropic"] is False

    provider_keys.remove_key("glm", actor=admin)
    state = {k["provider"]: k["configured"] for k in provider_keys.list_keys()}
    assert state["glm"] is False


def test_chave_fica_cifrada(admin):
    from sqlalchemy import text

    from appaiforge.db import session_scope

    provider_keys.set_key("glm", "chave-secreta", actor=admin)
    with session_scope() as s:
        raw = s.execute(text("SELECT key_encrypted FROM provider_keys WHERE provider='glm'")).scalar_one()
    assert "chave-secreta" not in raw


def test_auditoria_de_chave_nao_guarda_valor(admin):
    provider_keys.set_key("openai", "sk-nao-vazar", actor=admin)
    entry = audit.list_global(action="provider_key.set")[0]
    assert entry["resource_id"] == "openai"
    assert "sk-nao-vazar" not in str(entry)
    assert "key" not in entry["details"]


def test_teste_de_chave_configurada(admin, monkeypatch):
    provider_keys.set_key("glm", "qualquer", actor=admin)
    monkeypatch.setattr(provider_keys, "_probe", lambda provider, key: (True, "ok"))
    ok, message = provider_keys.test_stored_key("glm")
    assert ok and message == "ok"


def test_teste_chave_nao_configurada(admin):
    ok, message = provider_keys.test_stored_key("anthropic")
    assert not ok and "não configurada" in message


def test_gestao_sem_permissao(clean_db):
    catalog.ensure_presets()
    editor = auth.create_user("ed@keys.local", "pw", UserType.editor.value)
    with pytest.raises(PermissionError):
        provider_keys.set_key("glm", "x", actor=editor)


def test_provedor_custom_aparece_no_catalogo(admin):
    catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1", actor=admin)
    state = {k["provider"]: k["configured"] for k in provider_keys.list_keys()}
    assert "minha-ia" in state and state["minha-ia"] is False
    provider_keys.set_key("minha-ia", "k", actor=admin)
    state = {k["provider"]: k["configured"] for k in provider_keys.list_keys()}
    assert state["minha-ia"] is True


def test_teste_provedor_custom_usa_base_url(admin, monkeypatch):
    catalog.create_provider("minha-ia", "Minha IA", "openai-compatible", "https://api.minha.ai/v1", actor=admin)
    provider_keys.set_key("minha-ia", "k", actor=admin)
    seen = {}

    def fake_probe(provider_def, key):
        seen["base_url"] = provider_def["base_url"]
        return True, "ok"

    monkeypatch.setattr(provider_keys, "_probe", fake_probe)
    ok, _ = provider_keys.test_stored_key("minha-ia")
    assert ok and seen["base_url"] == "https://api.minha.ai/v1"


def test_chat_url_por_provedor():
    assert provider_keys._chat_url({"id": "x", "base_url": "https://a/v1"}) == "https://a/v1/chat/completions"
    assert provider_keys._chat_url({"id": "x", "base_url": "https://a"}) == "https://a/v1/chat/completions"
    assert provider_keys._chat_url({"id": "openrouter", "base_url": None}) == "https://openrouter.ai/api/v1/chat/completions"