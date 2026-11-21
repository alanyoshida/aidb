"""Rota do webhook do GitLab (change add-deploy-only-system, tarefa 5.3)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from appaiforge import deploy
from appaiforge.deploy_routes import router


@pytest.fixture()
def setup(clean_db, monkeypatch):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system

    editor = auth.create_user("hook@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Hook", "hook-sys", kind=KIND_DEPLOY_ONLY)
    scheduled = []
    monkeypatch.setattr(deploy, "schedule_webhook_check", scheduled.append)
    app = FastAPI()
    app.include_router(router)
    return system, editor, deploy.webhook_secret(system.id), scheduled, TestClient(app)


def test_segredo_certo_agenda_a_verificacao(setup):
    system, _, secret, scheduled, client = setup
    resp = client.post(f"/hooks/gitlab/{system.id}", headers={"X-Gitlab-Token": secret}, json={"ref": "refs/tags/v1"})
    assert resp.status_code == 202
    assert scheduled == [system.id]


@pytest.mark.parametrize("headers", [{"X-Gitlab-Token": "errado"}, {}, {"X-Gitlab-Token": ""}])
def test_segredo_errado_ou_ausente_e_recusado_sem_efeito(setup, headers):
    system, _, _, scheduled, client = setup
    assert client.post(f"/hooks/gitlab/{system.id}", headers=headers, json={}).status_code == 401
    assert client.post("/hooks/gitlab/inexistente", headers=headers).status_code == 401
    assert scheduled == []


def test_segredo_de_outro_sistema_e_recusado(setup):
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system

    system, editor, _, scheduled, client = setup
    other = create_system(editor, "Outro", "hook-outro", kind=KIND_DEPLOY_ONLY)
    resp = client.post(f"/hooks/gitlab/{system.id}", headers={"X-Gitlab-Token": deploy.webhook_secret(other.id)})
    assert resp.status_code == 401 and scheduled == []


def test_corpo_com_tag_inexistente_nao_e_confiado(setup, monkeypatch):
    """A verificação ignora o corpo: só o que o repositório tem pode ser implantado."""
    from appaiforge.db import session_scope
    from appaiforge.models import DeploySettings, SystemStatus
    from appaiforge.services.systems import set_status

    system, _, secret, _, client = setup
    set_status(system.id, SystemStatus.active, "")
    with session_scope() as s:
        row = s.get(DeploySettings, system.id)
        row.mode, row.detection = "automatic", "webhook"
    monkeypatch.setattr(deploy, "schedule_webhook_check", deploy.webhook_check)
    monkeypatch.setattr(deploy, "remote_tags", lambda *a, **k: {})
    deployed = []
    monkeypatch.setattr(deploy, "deploy", lambda *a, **k: deployed.append((a, k)))
    body = {"object_kind": "tag_push", "ref": "refs/tags/v99.0.0", "checkout_sha": "f" * 40}
    assert client.post(f"/hooks/gitlab/{system.id}", headers={"X-Gitlab-Token": secret}, json=body).status_code == 202
    assert deployed == []


def test_trocar_o_segredo_invalida_o_anterior(setup):
    system, editor, secret, scheduled, client = setup
    new = deploy.rotate_webhook_secret(system, editor)
    assert new != secret
    assert client.post(f"/hooks/gitlab/{system.id}", headers={"X-Gitlab-Token": secret}).status_code == 401
    assert client.post(f"/hooks/gitlab/{system.id}", headers={"X-Gitlab-Token": new}).status_code == 202
