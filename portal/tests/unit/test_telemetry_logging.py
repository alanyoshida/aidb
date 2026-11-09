"""Unitários dos logs estruturados da change agent-telemetry-otel: login,
mudanças de configuração de sistema (rede e ciclo de vida) e o espelho das
ações administrativas em `services/audit.py` — todos via o logger único
`telemetry.get_logger()` (nome fixo `appaiforge.telemetry`)."""

import logging

import pytest

from appaiforge import auth, telemetry
from appaiforge.services import audit, network_policy
from appaiforge.services.systems import create_system, set_status
from appaiforge.models import SystemStatus, UserType


@pytest.fixture(autouse=True)
def _capture_telemetry_logs(caplog):
    caplog.set_level(logging.INFO, logger=telemetry.LOGGER_NAME)


# --- login (task 7.1) ----------------------------------------------------

def test_login_bem_sucedido_gera_uma_entrada_de_log(clean_db, caplog):
    auth.create_user("login-log@t.local", "senha-boa", UserType.editor.value)
    caplog.clear()

    auth.authenticate("login-log@t.local", "senha-boa")

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].result == "sucesso"
    assert records[0].email == "login-log@t.local"
    assert "senha-boa" not in records[0].getMessage()


def test_tentativa_de_login_invalida_gera_uma_entrada_de_log_sem_senha(clean_db, caplog):
    auth.create_user("login-log2@t.local", "senha-boa", UserType.editor.value)
    caplog.clear()

    with pytest.raises(auth.LoginRejected):
        auth.authenticate("login-log2@t.local", "senha-errada")

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].result == "falha"
    for record in records:
        assert "senha-errada" not in repr(record.__dict__)


# --- configuração de rede (task 8.1) -------------------------------------

@pytest.fixture()
def net_system(clean_db):
    editor = auth.create_user("net-log@t.local", "pw", UserType.editor.value)
    return editor, create_system(editor, "NetLog", "net-log-svc")


def test_set_internet_enabled_gera_log_com_sistema_autor_e_valor(net_system, caplog):
    editor, system = net_system
    caplog.clear()

    network_policy.set_internet_enabled(system.id, False, author_id=editor.id)

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].system_id == system.id
    assert records[0].author_id == editor.id
    assert records[0].enabled is False


def test_set_restricted_network_gera_log_com_sistema_autor_e_valor(net_system, caplog):
    editor, system = net_system
    caplog.clear()

    network_policy.set_restricted_network(system.id, True, author_id=editor.id)

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert any(r.restricted is True and r.system_id == system.id for r in records)


def test_add_allowed_domain_gera_log_com_dominio(net_system, caplog):
    editor, system = net_system
    caplog.clear()

    network_policy.add_allowed_domain(system.id, "api.exemplo.com", author_id=editor.id)

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].domain == "api.exemplo.com"
    assert records[0].author_id == editor.id


# --- ciclo de vida do sistema (task 9.1) ---------------------------------

def test_set_status_gera_log_de_mudanca_de_status(net_system, caplog):
    editor, system = net_system
    caplog.clear()

    set_status(system.id, SystemStatus.archived, "arquivado no teste")

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].system_id == system.id
    assert records[0].status == "archived"


def test_archive_system_gera_log_com_ator(net_system, caplog, monkeypatch):
    editor, system = net_system
    from appaiforge import provisioning

    monkeypatch.setattr(provisioning, "stop_and_remove", lambda *_a, **_k: None)
    monkeypatch.setattr(provisioning, "unpublish_app", lambda *_a, **_k: None)
    caplog.clear()

    provisioning.archive_system(system, actor_id=editor.id, actor_email=editor.email)

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME and r.getMessage() == "sistema arquivado"]
    assert len(records) == 1
    assert records[0].actor_id == editor.id
    assert records[0].system_id == system.id


def test_delete_system_gera_log_antes_da_remocao_de_dados(net_system, caplog, monkeypatch, tmp_path):
    editor, system = net_system
    from appaiforge import provisioning
    from appaiforge.config import get_settings

    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(provisioning, "stop_and_remove", lambda *_a, **_k: None)
    monkeypatch.setattr(provisioning, "unpublish_app", lambda *_a, **_k: None)
    caplog.clear()

    provisioning.delete_system(system, actor_id=editor.id, actor_email=editor.email)
    get_settings.cache_clear()

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].actor_id == editor.id
    assert records[0].system_id == system.id


# --- espelho da auditoria de gestão em log (task 11.1) -------------------

def test_audit_record_grava_em_postgres_e_espelha_no_log(net_system, caplog):
    editor, system = net_system
    caplog.clear()

    row = audit.record(
        actor_id=editor.id, actor_email=editor.email, action="system.revoke_inference",
        resource_type="system", resource_id=system.id, system_id=system.id,
        details={"motivo": "teste", "api_key": "segredo-nao-pode-aparecer"},
    )

    # Postgres continua gravando como antes (comportamento inalterado)
    assert row.id is not None
    assert "api_key" not in row.details

    records = [r for r in caplog.records if r.name == telemetry.LOGGER_NAME]
    assert len(records) == 1
    assert records[0].action == "system.revoke_inference"
    assert records[0].actor_id == editor.id
    assert "api_key" not in records[0].details
    assert "segredo-nao-pode-aparecer" not in repr(records[0].details)
