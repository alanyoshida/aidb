"""Teste de conexão BigQuery (spec db-bigquery): JSON validado sempre, acesso verificado no dataset
sem executar query (funciona no BigQuery real e no emulador do E2E, que não suporta
INFORMATION_SCHEMA e fazia o client recriar o job indefinidamente)."""

import json

import pytest

from appaiforge.services import connections
from appaiforge.services.connections import ConnectionFailed

SA = json.dumps({"type": "service_account", "client_email": "sa@p.iam.gserviceaccount.com"})


class _FakeClient:
    calls: list = []
    fail: Exception | None = None

    def __init__(self, project, credentials):
        _FakeClient.calls.append(("init", project, type(credentials).__name__))

    def get_dataset(self, ref, timeout=None):
        _FakeClient.calls.append(("get_dataset", ref, timeout))
        if _FakeClient.fail:
            raise _FakeClient.fail
        return object()

    def query(self, *a, **k):  # não deve ser usado
        raise AssertionError("o teste de conexão não deve executar query")


@pytest.fixture()
def fake_bq(monkeypatch):
    from google.cloud import bigquery

    _FakeClient.calls = []
    _FakeClient.fail = None
    monkeypatch.setattr(bigquery, "Client", _FakeClient)
    monkeypatch.setenv("BIGQUERY_EMULATOR_HOST", "http://emu:9050")
    return _FakeClient


def test_json_malformado_e_recusado_mesmo_no_emulador(fake_bq):
    with pytest.raises(ConnectionFailed, match="JSON inválido"):
        connections._test_bigquery("p", "d", "não-é-json")
    assert fake_bq.calls == []


def test_json_sem_client_email_e_recusado(fake_bq):
    with pytest.raises(ConnectionFailed, match="JSON inválido"):
        connections._test_bigquery("p", "d", json.dumps({"type": "service_account"}))


def test_acesso_verificado_no_dataset_sem_query(fake_bq):
    connections._test_bigquery("bq-test", "e2e", SA)
    assert ("get_dataset", "bq-test.e2e", 15) in fake_bq.calls


def test_dataset_inacessivel_vira_connection_failed(fake_bq):
    fake_bq.fail = RuntimeError("404 Not found: Dataset bq-test:nao")
    with pytest.raises(ConnectionFailed, match="não foi possível conectar ao BigQuery"):
        connections._test_bigquery("bq-test", "nao", SA)
