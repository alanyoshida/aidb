"""Regras de versão e do modo automático (change add-deploy-only-system, tarefas 3.2 e 5.1)."""

import pytest

from appaiforge import deploy


def test_ordem_de_versao_compara_numeros_como_numeros():
    tags = {"v1.0.1": "a", "v1.0.10": "b", "v1.0.2": "c", "rascunho": "d"}
    assert [name for name, _ in deploy.filter_and_sort(tags, "v*")] == ["v1.0.10", "v1.0.2", "v1.0.1"]


def test_filtro_pelo_padrao_e_desempate_estavel():
    tags = {"v2.0.0": "a", "release-3": "b", "v2.0.0-rc1": "c", "v10.0.0": "d"}
    assert [n for n, _ in deploy.filter_and_sort(tags, "v*")] == ["v10.0.0", "v2.0.0-rc1", "v2.0.0"]
    assert [n for n, _ in deploy.filter_and_sort(tags, "release-*")] == ["release-3"]


@pytest.fixture()
def system(clean_db):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system

    editor = auth.create_user("auto@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Auto", "auto-regra", kind=KIND_DEPLOY_ONLY)


def _record(system, tag: str, status: str) -> None:
    from appaiforge.db import session_scope
    from appaiforge.models import Deployment

    with session_scope() as s:
        s.add(Deployment(system_id=system.id, tag=tag, trigger="manual", status=status, commit_sha="x"))


TAGS = {"v1.2.0": "a", "v1.3.0": "b"}


def test_tag_nova_e_escolhida(system):
    _record(system, "v1.2.0", "succeeded")
    assert deploy.newest_undeployed(system, TAGS, "v*") == "v1.3.0"


def test_rollback_manual_permanece(system):
    _record(system, "v1.2.0", "succeeded")
    _record(system, "v1.3.0", "succeeded")
    _record(system, "v1.2.0", "succeeded")  # volta manual
    assert deploy.newest_undeployed(system, TAGS, "v*") is None


def test_tag_que_falhou_nao_e_repetida(system):
    _record(system, "v1.3.0", "failed")
    assert deploy.newest_undeployed(system, TAGS, "v*") is None


def test_modo_manual_nao_implanta(system, monkeypatch):
    called = []
    monkeypatch.setattr(deploy, "remote_tags", lambda *a, **k: called.append(1) or TAGS)
    monkeypatch.setattr(deploy, "deploy", lambda *a, **k: called.append(2))
    assert deploy.check_for_new(system, deploy.TRIGGER_POLLING) is None
    assert called == []


def test_modo_automatico_implanta_a_tag_nova(system, monkeypatch):
    from appaiforge.db import session_scope
    from appaiforge.models import DeploySettings

    with session_scope() as s:
        s.get(DeploySettings, system.id).mode = "automatic"
    monkeypatch.setattr(deploy, "remote_tags", lambda *a, **k: TAGS)
    calls = []
    monkeypatch.setattr(deploy, "deploy", lambda sys, tag, trigger: calls.append((tag, trigger)) or {"tag": tag})
    assert deploy.check_for_new(system, deploy.TRIGGER_POLLING) == {"tag": "v1.3.0"}
    assert calls == [("v1.3.0", "polling")]


def test_versao_com_requirements_sem_uv_lock_e_recusada_antes_da_troca(system, monkeypatch):
    """Piloto: a app declarava as dependências só em requirements.txt; a produção, que instala só
    pelo uv.lock, subiu a app sem nada e ela morreu na importação. Agora a versão é recusada antes
    de o workspace trocar, com o motivo."""
    from types import SimpleNamespace

    from appaiforge import checkpoints, git_sync

    files = {"app/main.py": "m", "app/requirements.txt": "nicegui\n"}
    monkeypatch.setattr(deploy, "_load_secrets", lambda s: SimpleNamespace())
    monkeypatch.setattr(checkpoints, "ensure_repo", lambda s: None)
    monkeypatch.setattr(git_sync, "system_tip", lambda s: None)
    monkeypatch.setattr(deploy, "verify_and_fetch", lambda s, tag, secrets: "a" * 40)
    monkeypatch.setattr(deploy, "_git_object", lambda s, sha, path: files.get(path))

    def no_switch(*_a, **_k):
        raise AssertionError("não pode trocar o workspace")

    monkeypatch.setattr(deploy, "_switch", no_switch)
    view = deploy._deploy_locked(system, "v1.0.6", "manual", None)
    assert view["status"] == "failed"
    assert "requirements.txt" in view["detail"] and "uv.lock" in view["detail"]
