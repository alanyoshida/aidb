"""Unitários do entrypoint do sidecar (task 5.1) — sem rede real."""

import sidecar


def test_allow_list_from_env_parseia_pares_host_porta(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", '[["openrouter.ai", 443], ["pypi.org", 443]]')
    allow = sidecar.allow_list_from_env()
    assert allow.permits("openrouter.ai", 443)
    assert allow.permits("pypi.org", 443)
    assert not allow.permits("example.com", 443)


def test_allow_list_from_env_vazia_por_default(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    allow = sidecar.allow_list_from_env()
    assert not allow.permits("qualquer.com", 443)


def test_port_from_env_usa_default_15500(monkeypatch):
    monkeypatch.delenv("LISTEN_PORT", raising=False)
    assert sidecar.port_from_env() == 15500


def test_port_from_env_le_a_env(monkeypatch):
    monkeypatch.setenv("LISTEN_PORT", "19999")
    assert sidecar.port_from_env() == 19999
