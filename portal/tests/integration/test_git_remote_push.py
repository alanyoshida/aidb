"""Envio dos checkpoints e vínculo inicial (change add-system-git-remote, tarefas 3.6 e 3.7),
contra o servidor git por SSH da fixture."""

import os

import pytest

pytestmark = [pytest.mark.integration]


def _write(system, name: str, content: str) -> None:
    from appaiforge.checkpoints import workspace_dir

    path = os.path.join(workspace_dir(system), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.fixture()
def ready(docker_env, clean_db, git_ssh_server, monkeypatch):
    """Sistema com um checkpoint, configurado para o repositório da fixture, chave autorizada e
    identidade do servidor confirmada (vínculo ainda não ativado)."""
    from appaiforge import auth, checkpoints, git_sync
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import git_remote
    from appaiforge.services.systems import create_system

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    get_settings.cache_clear()
    owner = auth.create_user("push@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Push", f"push-{os.urandom(3).hex()}")
    _write(system, "app/main.py", "print('v1')\n")
    checkpoints.record_checkpoint(system, None, "v1", owner)
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    git_ssh_server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    return system, owner


def test_ativar_com_remoto_vazio_cria_a_branch_de_trabalho(ready, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = ready
    view = git_sync.activate(system, owner)
    assert view["enabled"] and view["state"] == "synced"
    local = checkpoints._git(system, "rev-parse", "HEAD")
    assert git_ssh_server.git("rev-parse", "refs/heads/homolog") == local
    assert view["last_pushed_sha"] == local


def test_checkpoint_chega_ao_remoto_com_o_editor_como_autor(ready, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = ready
    git_sync.activate(system, owner)
    _write(system, "app/main.py", "print('v2')\n")
    cp = checkpoints.record_checkpoint(system, None, "v2 pelo chat", owner)
    result = git_sync.push_now(system, owner)
    assert result["sent"] == cp.git_sha
    assert git_ssh_server.git("log", "-1", "--format=%ae|%s", "homolog") == f"{owner.email}|v2 pelo chat"
    assert git_sync.push_now(system, owner)["sent"] is None, "nada novo, nada enviado"


def test_restauracao_tambem_e_enviada_e_nada_e_reescrito(ready, git_ssh_server):
    from appaiforge import checkpoints, git_sync

    system, owner = ready
    git_sync.activate(system, owner)
    v1 = checkpoints._git(system, "rev-parse", "HEAD")
    _write(system, "app/main.py", "print('v2')\n")
    v2 = checkpoints.record_checkpoint(system, None, "v2", owner).git_sha
    git_sync.push_now(system, owner)
    restored = checkpoints.rollback(system, v1, owner)
    git_sync.push_now(system, owner)
    assert git_ssh_server.git("rev-parse", "homolog") == restored.git_sha
    git_ssh_server.git("merge-base", "--is-ancestor", v2, "homolog")  # v2 continua no histórico


def test_remoto_com_commits_novos_nao_e_sobrescrito(ready, git_ssh_server):
    from appaiforge import checkpoints, git_sync
    from appaiforge.services import git_remote

    system, owner = ready
    git_sync.activate(system, owner)
    human = git_ssh_server.commit_as_human("homolog", {"humano.txt": "merge humano\n"}, "merge humano")
    _write(system, "app/main.py", "print('v2')\n")
    checkpoints.record_checkpoint(system, None, "v2", owner)
    result = git_sync.push_now(system, owner)
    assert result["kind"] == "needs_sync"
    assert git_ssh_server.git("rev-parse", "homolog") == human, "o remoto não foi reescrito"
    view = git_remote.get_view(system)
    assert view["state"] == "pending" and "remoto" in view["state_detail"]


def test_vinculo_recusado_com_historico_sem_relacao(ready, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.services import git_remote

    system, owner = ready
    git_ssh_server.init_repo(with_branches=("main", "homolog"))  # histórico próprio do remoto
    before = git_ssh_server.git("rev-parse", "homolog")
    with pytest.raises(git_sync.UnrelatedHistory):
        git_sync.activate(system, owner)
    assert git_remote.get_view(system)["enabled"] is False
    assert git_ssh_server.git("rev-parse", "homolog") == before


def test_remoto_fora_do_ar_deixa_envio_pendente(ready, git_ssh_server):
    from appaiforge import checkpoints, git_sync
    from appaiforge.services import git_remote

    system, owner = ready
    git_sync.activate(system, owner)
    _write(system, "app/main.py", "print('v2')\n")
    checkpoints.record_checkpoint(system, None, "v2", owner)
    git_ssh_server.stop()
    try:
        result = git_sync.push_now(system, owner)
    finally:
        git_ssh_server.start()
    assert result["kind"] == "unreachable"
    assert git_remote.get_view(system)["state"] == "pending"
    assert git_sync.push_now(system, owner)["sent"] is not None, "reenvio quando o remoto volta"
    assert git_remote.get_view(system)["state"] == "synced"


def _run_and_wait(queue, system, owner, prompt: str, timeout: float = 60.0) -> str:
    import time

    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, RunStatus

    run = queue.enqueue(system.id, owner.id, prompt)
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            status = s.get(AgentRun, run.id).status
        if status in (RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted):
            return status.value
        time.sleep(0.2)
    raise AssertionError("execução não terminou a tempo")


def _wait_for(predicate, timeout: float = 45.0) -> bool:
    """O status `succeeded` é gravado antes do checkpoint e do envio, que vêm logo depois na
    mesma thread: espera o efeito em vez de conferir no instante seguinte."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    return False


def test_execucao_do_agente_envia_e_falha_de_remoto_nao_derruba_a_execucao(ready, git_ssh_server, docker_env):
    """Tarefa 3.8: o checkpoint de uma execução bem-sucedida é enviado; com o remoto fora do ar a
    execução termina normalmente, o envio fica pendente e sai junto com o checkpoint seguinte."""
    from appaiforge import checkpoints, git_sync
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.harness.fake import FakeHarness
    from appaiforge.services import git_remote

    system, owner = ready
    git_sync.activate(system, owner)
    queue = AgentQueue(FakeHarness(str(docker_env / "workspaces"), step_delay=0))

    assert _run_and_wait(queue, system, owner, "crie o painel de clientes") == "succeeded"
    assert _wait_for(lambda: git_ssh_server.git("rev-parse", "homolog") == checkpoints._git(system, "rev-parse", "HEAD"))

    git_ssh_server.stop()
    try:
        assert _run_and_wait(queue, system, owner, "anote primeira nota") == "succeeded"
        assert _wait_for(lambda: git_remote.get_view(system)["state"] == "pending"), git_remote.get_view(system)
    finally:
        git_ssh_server.start()
    pending_tip = checkpoints._git(system, "rev-parse", "HEAD")
    assert git_ssh_server.git("rev-parse", "homolog") != pending_tip

    assert _run_and_wait(queue, system, owner, "anote segunda nota") == "succeeded"
    assert _wait_for(lambda: git_remote.get_view(system)["state"] == "synced")
    tip = checkpoints._git(system, "rev-parse", "HEAD")
    assert git_ssh_server.git("rev-parse", "homolog") == tip
    git_ssh_server.git("merge-base", "--is-ancestor", pending_tip, "homolog")
    assert git_remote.get_view(system)["state"] == "synced"


def test_depois_de_enviar_a_promocao_nao_ve_pendencia(ready, git_ssh_server):
    """Achado no E2E com GitLab: depois de um envio, a posição conhecida da branch remota tem de
    acompanhar o que foi enviado, ou a promoção acusa checkpoints "não enviados"."""
    from appaiforge import checkpoints, git_sync

    system, owner = ready
    git_sync.activate(system, owner)
    _write(system, "app/main.py", "print('v2')\n")
    checkpoints.record_checkpoint(system, None, "v2", owner)
    git_sync.push_now(system, owner)
    assert git_sync.unsent_checkpoints(system) == []
    result = git_sync.request_promotion(system, owner)
    assert result["fallback"] and "/-/merge_requests/new?" in result["url"]
