"""Migração do histórico de um sistema anterior à mudança de local do repositório (change
`isolate-workspace-repository`, design D4; requirement "Histórico existente preservado na
mudança de local"). Driver Docker; o equivalente Kubernetes está em
`test_workspace_repository_isolation.py`/`test_driver_parity.py`."""

import os
import subprocess

import pytest

pytestmark = [pytest.mark.integration]


def _legacy_git(ws: str, *args: str) -> str:
    """Git no formato ANTIGO (`.git` dentro do workspace), só para montar o cenário."""
    env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def _write(ws: str, name: str, content: str) -> None:
    with open(os.path.join(ws, name), "w") as f:
        f.write(content)


@pytest.fixture()
def legacy_system(docker_env, clean_db):
    """Sistema com `.git` no workspace, dois checkpoints registrados e a ref adulterada."""
    from appaiforge import auth
    from appaiforge.checkpoints import workspace_dir
    from appaiforge.db import session_scope
    from appaiforge.models import Checkpoint, UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("migr@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Migr", f"migr-{os.urandom(3).hex()}")
    ws = workspace_dir(system)
    os.makedirs(ws)
    _legacy_git(ws, "init", "-q", "-b", "main")

    shas = []
    for version in ("v1", "v2"):
        _write(ws, "app.txt", f"{version}\n")
        _legacy_git(ws, "add", "-A")
        _legacy_git(ws, "commit", "-q", "-m", version)
        sha = _legacy_git(ws, "rev-parse", "HEAD")
        shas.append(sha)
        with session_scope() as s:
            s.add(Checkpoint(system_id=system.id, run_id=None, git_sha=sha, message=version,
                             author_id=editor.id, author_email=editor.email))
        import time
        time.sleep(0.01)  # created_at distinto entre os dois checkpoints

    # o "agente" cria um commit por conta própria e aponta a branch antiga para ele
    _write(ws, "app.txt", "do-agente\n")
    _legacy_git(ws, "add", "-A")
    _legacy_git(ws, "commit", "-q", "-m", "commit plantado")
    planted = _legacy_git(ws, "rev-parse", "HEAD")
    _write(ws, "app.txt", "v2\n")  # árvore de trabalho igual ao último checkpoint
    return system, ws, shas, planted


def test_historico_migrado_adota_o_ultimo_checkpoint_registrado(legacy_system):
    from appaiforge import checkpoints

    system, ws, (v1, v2), planted = legacy_system
    checkpoints.ensure_repo(system)

    assert checkpoints._git(system, "rev-parse", "HEAD") == v2, "a branch nova aponta para o checkpoint registrado, não para a ref adulterada"
    assert planted != v2
    assert checkpoints._git(system, "status", "--porcelain") == "", "árvore de trabalho igual ao último checkpoint"
    assert os.path.isdir(os.path.join(ws, ".git")), "o .git antigo fica intocado no workspace"
    assert checkpoints.commit_all(system, "nada mudou") is None


def test_checkpoint_antigo_restauravel_depois_da_migracao(legacy_system):
    from appaiforge import checkpoints

    system, ws, (v1, v2), _ = legacy_system
    checkpoints.ensure_repo(system)
    checkpoints.rollback(system, v1)
    with open(os.path.join(ws, "app.txt")) as f:
        assert f.read() == "v1\n"


def test_sem_checkpoint_registrado_repositorio_nasce_vazio(docker_env, clean_db):
    from appaiforge import auth, checkpoints
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("migr-vazio@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "MigrVazio", f"migr-vazio-{os.urandom(3).hex()}")
    ws = checkpoints.workspace_dir(system)
    os.makedirs(ws)
    _legacy_git(ws, "init", "-q", "-b", "main")
    _write(ws, "app.txt", "x\n")
    _legacy_git(ws, "add", "-A")
    _legacy_git(ws, "commit", "-q", "-m", "nunca registrado")

    cp = checkpoints.record_checkpoint(system, None, "primeiro no repositório novo")
    assert cp is not None
    assert checkpoints._git(system, "rev-list", "--count", "HEAD") == "1"


def test_objetos_nao_regulares_e_alternates_nao_sao_copiados(legacy_system, tmp_path):
    from appaiforge import checkpoints
    from appaiforge.git_backend import DockerGitBackend

    system, ws, _, _ = legacy_system
    objects = os.path.join(ws, ".git", "objects")
    os.makedirs(os.path.join(objects, "info"), exist_ok=True)
    with open(os.path.join(objects, "info", "alternates"), "w") as f:
        f.write(str(tmp_path) + "\n")
    os.makedirs(os.path.join(objects, "ab"), exist_ok=True)
    os.symlink("/etc/passwd", os.path.join(objects, "ab", "c" * 38))

    checkpoints.ensure_repo(system)
    new_objects = os.path.join(DockerGitBackend().git_dir(system), "objects")
    assert not os.path.exists(os.path.join(new_objects, "info", "alternates"))
    assert not os.path.lexists(os.path.join(new_objects, "ab", "c" * 38))


def _system_with_checkpoint(email: str):
    from appaiforge import auth, checkpoints
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user(email, "pw", UserType.editor.value)
    system = create_system(editor, "Excl", f"excl-{os.urandom(3).hex()}")
    ws = checkpoints.workspace_dir(system)
    os.makedirs(ws)
    _write(ws, "app.txt", "x\n")
    assert checkpoints.record_checkpoint(system, None, "primeiro") is not None
    return system


def test_exclusao_definitiva_remove_o_repositorio(docker_env, clean_db):
    """Requirement "Exclusão definitiva remove o repositório"."""
    from appaiforge.git_backend import DockerGitBackend
    from appaiforge.provisioning import delete_system

    system = _system_with_checkpoint("excl@t.local")
    git_dir = DockerGitBackend().git_dir(system)
    assert os.path.isdir(git_dir)
    delete_system(system)
    assert not os.path.exists(git_dir)


def test_arquivamento_preserva_o_repositorio(docker_env, clean_db):
    from appaiforge import checkpoints
    from appaiforge.git_backend import DockerGitBackend
    from appaiforge.provisioning import archive_system

    system = _system_with_checkpoint("arq@t.local")
    archive_system(system)
    assert os.path.isfile(os.path.join(DockerGitBackend().git_dir(system), "HEAD"))
    assert len(checkpoints.list_checkpoints(system)) == 1


def test_exclusao_definitiva_remove_vinculo_chave_token_e_retransmissao(docker_env, clean_db, monkeypatch):
    """change add-system-git-remote, requirement "Exclusão definitiva remove vínculo e chave"."""
    from appaiforge.config import get_settings
    from appaiforge.provisioning import delete_system
    from appaiforge.services import git_remote

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    get_settings.cache_clear()
    system = _system_with_checkpoint("excl-remoto@t.local")
    from appaiforge.db import session_scope
    from appaiforge.models import User
    with session_scope() as s:
        owner = s.get(User, system.owner_id)
        s.expunge(owner)
    git_remote.configure(system, owner, url="git@gitlab.exemplo.com:time/app.git")
    git_remote.set_api_token(system, owner, "tok-teste-exclusao")
    relay = os.path.join(get_settings().git_relays_dir, system.slug)
    os.makedirs(os.path.join(relay, "objects"))

    delete_system(system)

    assert git_remote.get_view(system) is None
    assert git_remote.load_secrets(system.id) is None
    assert not os.path.exists(relay)
