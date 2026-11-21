"""Sincronização, alterações não salvas e divergência (change add-system-git-remote, grupos 5-7),
contra o servidor git por SSH da fixture. O humano faz commits direto no remoto."""

import os
import time

import pytest

pytestmark = [pytest.mark.integration]


def _write(system, name: str, content: str) -> None:
    from appaiforge.checkpoints import workspace_dir

    path = os.path.join(workspace_dir(system), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _read(system, name: str) -> str | None:
    from appaiforge.checkpoints import workspace_dir

    path = os.path.join(workspace_dir(system), name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


@pytest.fixture()
def linked(docker_env, clean_db, git_ssh_server, monkeypatch):
    """Sistema com vínculo ativo: checkpoint inicial já na homolog do remoto."""
    from appaiforge import auth, checkpoints, git_sync
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import git_remote
    from appaiforge.services.systems import create_system

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    get_settings.cache_clear()
    owner = auth.create_user("sync@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Sync", f"sync-{os.urandom(3).hex()}")
    _write(system, "app/main.py", "linha 1\nlinha 2\nlinha 3\n")
    checkpoints.record_checkpoint(system, None, "inicial", owner)
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    git_ssh_server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    git_sync.activate(system, owner)
    return system, owner


def _view(system):
    from appaiforge.services import git_remote

    return git_remote.get_view(system)


# --- grupo 5: sincronização ------------------------------------------------------------------


def test_avanco_rapido_traz_o_merge_humano_e_registra_checkpoint(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    human = git_ssh_server.commit_as_human("homolog", {"humano.txt": "do merge request\n"}, "merge humano")
    result = git_sync.sync(system, owner)
    assert result == {"integrated": True, "sha": human}
    assert _read(system, "humano.txt") == "do merge request\n"
    newest = checkpoints.list_checkpoints(system)[0]
    assert newest["origin"] == "remote" and newest["git_sha"] == human
    assert git_sync.sync(system, owner) == {"integrated": False}


def test_merge_sem_conflito_combina_e_envia(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    _write(system, "app/outro.py", "local\n")
    checkpoints.record_checkpoint(system, None, "local", owner)
    git_sync.after_checkpoint(system, owner)
    assert _read(system, "humano.txt") == "x\n" and _read(system, "app/outro.py") == "local\n"
    assert _view(system)["state"] == "synced"
    tip = checkpoints._git(system, "rev-parse", "HEAD")
    assert git_ssh_server.git("rev-parse", "homolog") == tip
    assert len(checkpoints._git(system, "rev-list", "--parents", "-1", "HEAD").split()) == 3, "commit de merge"


def test_execucao_parte_do_codigo_mergeado(linked, git_ssh_server, docker_env):
    from appaiforge import git_sync
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.harness.base import RunEvent
    from appaiforge.harness.fake import FakeHarness

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "antes da execução\n"}, "merge humano")
    seen = {}

    class Spy(FakeHarness):
        def run(self, system_dict, session_id, prompt, on_event):
            seen["humano"] = _read(system, "humano.txt")
            super().run(system_dict, session_id, prompt, on_event)

    queue = AgentQueue(Spy(str(docker_env / "workspaces"), step_delay=0))
    run = queue.enqueue(system.id, owner.id, "crie o painel")
    _wait_run(run.id)
    assert seen["humano"] == "antes da execução\n"


def _wait_run(run_id: str, timeout: float = 60):
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, RunStatus

    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run.status in (RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted):
                return run.status.value, run.summary
        time.sleep(0.2)
    raise AssertionError("execução não terminou")


def test_remoto_fora_do_ar_antes_da_execucao_nao_impede(linked, git_ssh_server, docker_env):
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.harness.fake import FakeHarness

    system, owner = linked
    queue = AgentQueue(FakeHarness(str(docker_env / "workspaces"), step_delay=0))
    git_ssh_server.stop()
    try:
        status, _ = _wait_run(queue.enqueue(system.id, owner.id, "crie o painel").id)
    finally:
        git_ssh_server.start()
    assert status == "succeeded"


# --- grupo 6: alterações não salvas ----------------------------------------------------------


def test_alteracoes_nao_salvas_com_commits_a_trazer_bloqueiam_a_execucao(linked, git_ssh_server, docker_env):
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.harness.fake import FakeHarness

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    _write(system, "app/rascunho.py", "sobras de execução interrompida\n")
    called = {}

    class Spy(FakeHarness):
        def run(self, *args, **kwargs):
            called["harness"] = True
            super().run(*args, **kwargs)

    queue = AgentQueue(Spy(str(docker_env / "workspaces"), step_delay=0))
    status, summary = _wait_run(queue.enqueue(system.id, owner.id, "crie o painel").id)
    assert status == "failed" and "salve ou descarte" in summary
    assert "harness" not in called
    assert _read(system, "humano.txt") is None, "o workspace não muda"
    assert _read(system, "app/rascunho.py") == "sobras de execução interrompida\n"
    assert _view(system)["unsaved_blocked"] is True


def test_sem_commits_a_trazer_alteracoes_nao_salvas_nao_bloqueiam(linked):
    from appaiforge import git_sync

    system, owner = linked
    _write(system, "app/rascunho.py", "x\n")
    assert git_sync.before_run(system, owner) is None


def test_salvar_alteracoes_nao_salvas_e_seguir(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    _write(system, "app/rascunho.py", "guardar\n")
    with pytest.raises(git_sync.UnsavedChanges):
        git_sync.sync(system, owner)
    git_sync.save_unsaved(system, owner)
    assert _read(system, "app/rascunho.py") == "guardar\n" and _read(system, "humano.txt") == "x\n"
    assert _view(system)["unsaved_blocked"] is False
    assert git_ssh_server.git("rev-parse", "homolog") == checkpoints._git(system, "rev-parse", "HEAD")


def test_descartar_alteracoes_nao_salvas_e_seguir(linked, git_ssh_server):
    from appaiforge import git_sync

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    _write(system, "app/rascunho.py", "jogar fora\n")
    _write(system, "app/main.py", "editado sem checkpoint\n")
    git_sync.discard_unsaved(system, owner)
    assert _read(system, "app/rascunho.py") is None
    assert _read(system, "app/main.py") == "linha 1\nlinha 2\nlinha 3\n"
    assert _read(system, "humano.txt") == "x\n"


# --- grupo 7: divergência --------------------------------------------------------------------


def _diverge(system, owner, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    git_ssh_server.commit_as_human("homolog", {"app/main.py": "linha 1\nREMOTO\nlinha 3\n"}, "merge humano")
    _write(system, "app/main.py", "linha 1\nLOCAL\nlinha 3\n")
    local = checkpoints.record_checkpoint(system, None, "alteração local", owner)
    git_sync.after_checkpoint(system, owner)
    return local


def test_conflito_deixa_divergente_sem_marcas_e_suspende_envios(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    remote_before = None
    local = _diverge(system, owner, git_ssh_server)
    view = _view(system)
    assert view["state"] == "diverged" and view["conflict_files"] == ["app/main.py"]
    assert _read(system, "app/main.py") == "linha 1\nLOCAL\nlinha 3\n", "sem marcas de conflito no workspace"
    remote_before = git_ssh_server.git("rev-parse", "homolog")
    _write(system, "app/novo.py", "x\n")
    checkpoints.record_checkpoint(system, None, "mais local", owner)
    git_sync.after_checkpoint(system, owner)
    assert git_ssh_server.git("rev-parse", "homolog") == remote_before, "envios suspensos"
    assert git_sync.before_run(system, owner) is None, "o chat continua disponível"


def test_resolucao_no_workspace_concluida(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    _diverge(system, owner, git_ssh_server)
    files = git_sync.resolve_in_workspace(system, owner)
    assert files == ["app/main.py"]
    assert "<<<<<<<" in _read(system, "app/main.py")
    _write(system, "app/main.py", "linha 1\nLOCAL E REMOTO\nlinha 3\n")
    checkpoints.record_checkpoint(system, None, "resolve conflito", owner)
    git_sync.after_checkpoint(system, owner)
    assert _view(system)["state"] == "synced"
    tip = checkpoints._git(system, "rev-parse", "HEAD")
    assert git_ssh_server.git("rev-parse", "homolog") == tip


def test_resolucao_incompleta_nao_conclui(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    _diverge(system, owner, git_ssh_server)
    git_sync.resolve_in_workspace(system, owner)
    with pytest.raises(checkpoints.MergeIncomplete) as exc:
        checkpoints.record_checkpoint(system, None, "ainda com marcas", owner)
    assert exc.value.files == ["app/main.py"]
    assert _view(system)["state"] == "diverged"


def test_cancelar_resolucao_volta_ao_estado_local(linked, git_ssh_server):
    from appaiforge import git_sync

    system, owner = linked
    _diverge(system, owner, git_ssh_server)
    git_sync.resolve_in_workspace(system, owner)
    git_sync.cancel_resolution(system, owner)
    assert _read(system, "app/main.py") == "linha 1\nLOCAL\nlinha 3\n"
    assert _view(system)["state"] == "diverged" and not git_sync.merge_in_progress(system)


def test_adotar_a_versao_do_remoto(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    local = _diverge(system, owner, git_ssh_server)
    remote_tip = git_ssh_server.git("rev-parse", "homolog")
    pending = git_sync.unsent_checkpoints(system)
    assert [cp["git_sha"] for cp in pending] == [local.git_sha]
    git_sync.adopt_remote(system, owner)
    assert _read(system, "app/main.py") == "linha 1\nREMOTO\nlinha 3\n"
    assert _view(system)["state"] == "synced"
    assert git_ssh_server.git("rev-parse", "homolog") == remote_tip, "nada muda no remoto"
    checkpoints.rollback(system, local.git_sha, owner)
    assert _read(system, "app/main.py") == "linha 1\nLOCAL\nlinha 3\n", "o deixado de lado continua restaurável"


def test_sincronizar_agora_recusa_com_execucao_em_andamento(linked, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, RunStatus

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    with session_scope() as s:
        run = AgentRun(system_id=system.id, user_id=owner.id, user_email=owner.email, prompt="em curso",
                       status=RunStatus.running)
        s.add(run)
        s.flush()
        run_id = run.id
    with pytest.raises(git_sync.RunInProgress):
        git_sync.sync_now(system, owner)
    assert _read(system, "humano.txt") is None
    with session_scope() as s:
        s.get(AgentRun, run_id).status = RunStatus.succeeded
    assert git_sync.sync_now(system, owner)["integrated"] is True


def test_auditoria_de_sincronizacao_divergencia_e_saidas(linked, git_ssh_server):
    from sqlalchemy import select

    from appaiforge import git_sync
    from appaiforge.db import session_scope
    from appaiforge.models import ManagementAudit

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    git_sync.sync(system, owner)
    _diverge(system, owner, git_ssh_server)
    git_sync.resolve_in_workspace(system, owner)
    git_sync.cancel_resolution(system, owner)
    git_sync.adopt_remote(system, owner)
    with session_scope() as s:
        rows = s.execute(select(ManagementAudit).where(ManagementAudit.system_id == system.id)).scalars().all()
        actions = {(r.action, r.actor_email) for r in rows}
    for action in ("git_remote.sync", "git_remote.resolution_started", "git_remote.resolution_cancelled",
                   "git_remote.adopt_remote"):
        assert (action, owner.email) in actions, action


# --- grupo 8.2: definição de pipeline protegida ---------------------------------------------


def test_gitlab_ci_novo_fica_fora_do_envio(linked, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = linked
    _write(system, ".gitlab-ci.yml", "job: {script: [curl evil]}\n")
    _write(system, "app/main.py", "linha 1\nlinha 2 nova\nlinha 3\n")
    checkpoints.record_checkpoint(system, None, "com pipeline do agente", owner)
    git_sync.after_checkpoint(system, owner)
    assert ".gitlab-ci.yml" not in git_ssh_server.git("ls-tree", "--name-only", "homolog").split()
    from sqlalchemy import select

    from appaiforge.db import session_scope
    from appaiforge.models import ManagementAudit

    with session_scope() as s:
        warnings = [r.details.get("aviso", "") for r in s.execute(
            select(ManagementAudit).where(ManagementAudit.system_id == system.id,
                                          ManagementAudit.action == "git_remote.pipeline_file_ignored")).scalars()]
    assert len(warnings) == 1 and "deixado de fora" in warnings[0]
    assert _read(system, ".gitlab-ci.yml") is not None, "o arquivo continua no workspace"
    # não conta como alteração não salva
    git_ssh_server.commit_as_human("homolog", {"humano.txt": "x\n"}, "merge humano")
    assert git_sync.before_run(system, owner) is None
    assert _read(system, "humano.txt") == "x\n"


def test_gitlab_ci_vindo_do_remoto_e_preservado(linked, git_ssh_server):
    from sqlalchemy import select

    from appaiforge import checkpoints, git_sync
    from appaiforge.db import session_scope
    from appaiforge.models import ManagementAudit

    system, owner = linked
    git_ssh_server.commit_as_human("homolog", {".gitlab-ci.yml": "include: pipeline do time\n"}, "pipeline do time")
    git_sync.sync(system, owner)
    assert _read(system, ".gitlab-ci.yml") == "include: pipeline do time\n"
    _write(system, ".gitlab-ci.yml", "job: {script: [curl evil]}\n")
    _write(system, "app/main.py", "linha 1\nlinha 2 nova\nlinha 3\n")
    checkpoints.record_checkpoint(system, None, "agente mexe no pipeline", owner)
    git_sync.after_checkpoint(system, owner)
    assert git_ssh_server.exec("git", "--git-dir", "/srv/git/time/app.git", "show", "homolog:.gitlab-ci.yml") == "include: pipeline do time"
    assert _read(system, ".gitlab-ci.yml") == "include: pipeline do time\n"
    with session_scope() as s:
        actions = [r.action for r in s.execute(select(ManagementAudit).where(ManagementAudit.system_id == system.id)).scalars()]
    assert "git_remote.pipeline_file_ignored" in actions
