"""Trava do modo de autenticação e validação da config OIDC (change add-oidc-sso, task 1.4)."""

import pytest

from appaiforge import auth, auth_mode
from appaiforge.auth_mode import AuthConfigError, AuthModeMismatch
from appaiforge.config import Settings, get_settings
from appaiforge.db import session_scope
from appaiforge.models import PortalInstance


def _oidc_env(monkeypatch, **overrides):
    values = {
        "APPAIFORGE_AUTH_MODE": "oidc",
        "APPAIFORGE_OIDC_ISSUER": "http://idp/realms/aidb",
        "APPAIFORGE_OIDC_CLIENT_ID": "aidb-portal",
        "APPAIFORGE_OIDC_CLIENT_SECRET": "s3cr3t",
        "APPAIFORGE_PUBLIC_BASE_URL": "http://localhost:8082",
    }
    values.update(overrides)
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def test_default_e_local():
    assert Settings().auth_mode == "local"


def test_primeiro_boot_grava_o_modo(clean_db, monkeypatch):
    _oidc_env(monkeypatch)
    assert auth_mode.check_on_boot() == "oidc"
    with session_scope() as s:
        assert s.get(PortalInstance, 1).auth_mode == "oidc"


def test_modo_divergente_aborta(clean_db, monkeypatch):
    assert auth_mode.check_on_boot() == "local"
    _oidc_env(monkeypatch)
    with pytest.raises(AuthModeMismatch, match="diverge"):
        auth_mode.check_on_boot()


def test_base_existente_sem_trava_e_tratada_como_local(clean_db, monkeypatch):
    auth.create_user("velho@t.local", "pw", "admin")
    _oidc_env(monkeypatch)
    with pytest.raises(AuthModeMismatch):
        auth_mode.check_on_boot()


def test_config_oidc_incompleta_aborta_com_a_chave(clean_db, monkeypatch):
    _oidc_env(monkeypatch, APPAIFORGE_OIDC_CLIENT_SECRET="")
    with pytest.raises(AuthConfigError, match="APPAIFORGE_OIDC_CLIENT_SECRET"):
        auth_mode.check_on_boot()


def test_modo_invalido_aborta(clean_db, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_AUTH_MODE", "saml")
    get_settings.cache_clear()
    with pytest.raises(AuthConfigError, match="inválido"):
        auth_mode.check_on_boot()
