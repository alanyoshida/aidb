"""Backend git do repositório do sistema (change `isolate-workspace-repository`, design D1/D3):
o git roda com ambiente construído do zero, sem herdar nada do processo do portal."""

import os

import pytest

from appaiforge import auth, checkpoints
from appaiforge.git_backend import DockerGitBackend, git_env
from appaiforge.models import ExecutionMode, UserType
from appaiforge.services.systems import create_system


def test_git_env_nao_herda_do_processo(monkeypatch):
    monkeypatch.setenv("HOME", "/home/portal")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/portal/.config")
    monkeypatch.setenv("GIT_DIR", "/outro/repo")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.hooksPath'='/tmp/evil'")
    env = git_env("/gitdirs/x", "/workspaces/x")
    assert env["GIT_DIR"] == "/gitdirs/x"
    assert env["GIT_WORK_TREE"] == "/workspaces/x"
    assert env["HOME"] == "/nonexistent"
    assert env["XDG_CONFIG_HOME"] == "/nonexistent"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert "GIT_CONFIG_PARAMETERS" not in env
    assert set(env) == {
        "PATH", "LC_ALL", "HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
        "GIT_TERMINAL_PROMPT", "GIT_DIR", "GIT_WORK_TREE",
    }


def test_git_env_sem_arvore_de_trabalho():
    assert "GIT_WORK_TREE" not in git_env("/gitdirs/x", None)


@pytest.fixture()
def system(clean_db, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    editor = auth.create_user("gitbackend@t.local", "pw", UserType.editor.value)
    return create_system(editor, "GB", "git-backend")


def test_config_global_do_portal_e_ignorada(system, tmp_path, monkeypatch):
    """Uma config global do usuário que roda o portal (aqui: um alias e um hooksPath) não é lida."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = Portal Global\n[core]\n\thooksPath = /tmp/evil\n")
    monkeypatch.setenv("HOME", str(home))
    ws = checkpoints.workspace_dir(system)
    os.makedirs(ws)
    with open(os.path.join(ws, "a.txt"), "w") as f:
        f.write("a\n")
    checkpoints.ensure_repo(system)
    assert checkpoints._git(system, "config", "--get", "user.name") == "AIDB"
    assert checkpoints._git(system, "config", "--show-origin", "--get", "core.hooksPath").endswith("/dev/null")


def test_repositorio_fica_fora_do_workspace(system):
    ws = checkpoints.workspace_dir(system)
    os.makedirs(ws)
    with open(os.path.join(ws, "a.txt"), "w") as f:
        f.write("a\n")
    assert checkpoints.record_checkpoint(system, None, "primeiro") is not None
    assert not os.path.exists(os.path.join(ws, ".git")), "nenhum .git é criado no workspace"
    assert os.path.isfile(os.path.join(DockerGitBackend().git_dir(system), "HEAD"))


def test_identidade_de_execucao_por_modo(system):
    from appaiforge.git_backend import run_identity

    system.execution_mode = ExecutionMode.sandboxed
    assert run_identity(system) == (1000, 1000)
    system.execution_mode = ExecutionMode.reduced
    assert run_identity(system) == (1000, 1000)
    system.execution_mode = ExecutionMode.legacy
    assert run_identity(system) == (0, 0)


def test_normalize_ownership_nao_segue_link_nem_entra_no_git_antigo(tmp_path, monkeypatch):
    """Só a lógica de varredura (o `chown` real exige root): entradas do root mudam de dono, o
    `.git` da raiz fica de fora, e nada sob um link simbólico para fora do workspace é tocado."""
    from appaiforge import git_backend

    ws = tmp_path / "ws"
    (ws / "app").mkdir(parents=True)
    (ws / "app" / "main.py").write_text("x")
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / ".git" / "config").write_text("x")
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / "segredo").write_text("x")
    (ws / "link-para-fora").symlink_to(outside)

    real_stat = os.stat
    chowned = []

    def fake_stat(path, *, dir_fd=None, follow_symlinks=True):
        st = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 0, 0, *st[6:10]))

    def fake_chown(path, uid, gid, *, dir_fd=None, follow_symlinks=True):
        assert follow_symlinks is False
        chowned.append(os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), path))

    monkeypatch.setattr(git_backend.os, "stat", fake_stat)
    monkeypatch.setattr(git_backend.os, "chown", fake_chown)
    monkeypatch.setattr(git_backend.os, "fstat", lambda fd: os.stat_result((0,) * 4 + (1000,) + (0,) * 5))

    git_backend.normalize_ownership(str(ws), 1000, 1000)

    names = {os.path.relpath(p, ws) for p in chowned}
    assert names == {"app", "app/main.py", "link-para-fora"}, names
    assert not any(p.startswith(str(outside)) for p in chowned)
