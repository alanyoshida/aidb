"""Steps BDD de workspace-repository (change isolate-workspace-repository), driver Docker."""

import os
import subprocess
import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth, checkpoints
from appaiforge.git_backend import DockerGitBackend

scenarios("features/workspace_repository.feature")

_ctx: dict = {}


@pytest.fixture()
def ws_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path / "gitdirs"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "docker")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    _ctx.clear()
    _ctx["markers"] = str(tmp_path / "markers")
    os.makedirs(_ctx["markers"])
    return tmp_path


def _new_system(slug: str):
    from appaiforge.services.systems import create_system

    editor = auth.create_user(f"{slug}@wsr.local", "pw", "editor")
    _ctx["editor"] = editor
    system = create_system(editor, slug, slug)
    _ctx["system"] = system
    _ctx["ws"] = checkpoints.workspace_dir(system)
    os.makedirs(_ctx["ws"], exist_ok=True)
    return system


def _write(rel: str, content: str) -> None:
    path = os.path.join(_ctx["ws"], rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _legacy_git(*args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", _ctx["ws"], *args], capture_output=True, text=True,
                          check=True, env=env).stdout.strip()


@given("um sistema com um checkpoint")
def sistema_com_checkpoint(ws_env, clean_db):
    _new_system(f"wsr-{os.urandom(3).hex()}")
    _write("app/main.py", "print('v1')\n")
    _ctx["cp"] = checkpoints.record_checkpoint(_ctx["system"], None, "primeiro")
    assert _ctx["cp"] is not None


@given(parsers.parse('o agente cria um diretório ".git" no workspace com conteúdo próprio'))
def agente_cria_git():
    _write(".git/segredo-do-agente.txt", "plantado\n")
    _write(".git/HEAD", "ref: refs/heads/outra\n")


PLANTS = {
    "um hook pre-commit": lambda mk: (
        _write(".git/hooks/pre-commit", f"#!/bin/sh\ntouch {mk}/hook\n"),
        os.chmod(os.path.join(_ctx["ws"], ".git/hooks/pre-commit"), 0o755),
    ),
    "um filtro em .gitattributes": lambda mk: (
        _write(".git/config", f"[filter \"evil\"]\n\tclean = sh -c 'touch {mk}/filter; cat'\n"),
        _write(".gitattributes", "*.py filter=evil\n"),
    ),
    "um core.fsmonitor na config": lambda mk: (
        _write("fsmon.sh", f"#!/bin/sh\ntouch {mk}/fsmonitor\nexit 1\n"),
        os.chmod(os.path.join(_ctx["ws"], "fsmon.sh"), 0o755),
        _write(".git/config", f"[core]\n\tfsmonitor = {_ctx['ws']}/fsmon.sh\n"),
    ),
}


@given(parsers.parse('o agente planta "{what}" no workspace'))
def agente_planta(what):
    PLANTS[what](_ctx["markers"])


@when("um novo checkpoint é criado")
def novo_checkpoint():
    _write("app/main.py", "print('v2')\n")
    _ctx["cp2"] = checkpoints.record_checkpoint(_ctx["system"], None, "segundo")


@then("o repositório de checkpoints não está em nenhum caminho do workspace")
def repo_fora():
    git_dir = os.path.realpath(DockerGitBackend().git_dir(_ctx["system"]))
    ws = os.path.realpath(_ctx["ws"])
    assert not git_dir.startswith(ws + os.sep)
    assert not os.path.exists(os.path.join(ws, ".git"))
    for root, dirs, files in os.walk(ws):
        assert "HEAD" not in files or root == ws, f"repositório encontrado em {root}"


@then('o conteúdo do ".git" do workspace não entra no checkpoint')
def git_do_workspace_fora():
    assert _ctx["cp2"] is not None
    tracked = checkpoints._git(_ctx["system"], "ls-tree", "-r", "--name-only", "HEAD").split()
    assert not any(p.startswith(".git/") for p in tracked)
    assert checkpoints._git(_ctx["system"], "rev-parse", "--abbrev-ref", "HEAD") == "main"


@then("o checkpoint existe e nada plantado executou")
def nada_executou():
    assert _ctx["cp2"] is not None
    assert os.listdir(_ctx["markers"]) == []


@when("o dono restaura esse checkpoint depois de o agente apagar o arquivo")
def restaura_apos_apagar():
    os.remove(os.path.join(_ctx["ws"], "app/main.py"))
    checkpoints.rollback(_ctx["system"], _ctx["cp"].git_sha)


@then("o arquivo restaurado pode ser alterado pelo agente")
def restaurado_editavel():
    path = os.path.join(_ctx["ws"], "app/main.py")
    with open(path) as f:
        assert f.read() == "print('v1')\n"
    with open(path, "a") as f:
        f.write("# editado\n")


@given(parsers.parse('um sistema anterior à mudança, com checkpoints no ".git" do workspace'))
def sistema_legado(ws_env, clean_db):
    from appaiforge.db import session_scope
    from appaiforge.models import Checkpoint

    system = _new_system(f"wsr-leg-{os.urandom(3).hex()}")
    _legacy_git("init", "-q", "-b", "main")
    _ctx["shas"] = []
    for version in ("v1", "v2"):
        _write("app.txt", f"{version}\n")
        _legacy_git("add", "-A")
        _legacy_git("commit", "-q", "-m", version)
        sha = _legacy_git("rev-parse", "HEAD")
        _ctx["shas"].append(sha)
        with session_scope() as s:
            s.add(Checkpoint(system_id=system.id, run_id=None, git_sha=sha, message=version,
                             author_id=_ctx["editor"].id, author_email=_ctx["editor"].email))
        time.sleep(0.01)


@given(parsers.parse('o agente aponta a branch do ".git" antigo para um commit próprio'))
def agente_adultera_ref():
    _write("app.txt", "do-agente\n")
    _legacy_git("add", "-A")
    _legacy_git("commit", "-q", "-m", "plantado")
    _write("app.txt", "v2\n")


@when("o dono restaura o primeiro checkpoint registrado")
def restaura_primeiro():
    checkpoints.rollback(_ctx["system"], _ctx["shas"][0])


@then("o workspace volta ao estado daquele checkpoint")
def estado_restaurado():
    with open(os.path.join(_ctx["ws"], "app.txt")) as f:
        assert f.read() == "v1\n"


@when("o portal opera o repositório pela primeira vez")
def opera_primeira_vez():
    checkpoints.ensure_repo(_ctx["system"])


@then("o ponto atual é o último checkpoint registrado pelo portal")
def ponto_atual_registrado():
    assert checkpoints._git(_ctx["system"], "rev-parse", "HEAD") == _ctx["shas"][-1]


@when("um administrador exclui o sistema definitivamente")
def exclui():
    from appaiforge.provisioning import delete_system

    _ctx["git_dir"] = DockerGitBackend().git_dir(_ctx["system"])
    delete_system(_ctx["system"])


@then("o repositório git do sistema deixa de existir")
def repo_removido():
    assert not os.path.exists(_ctx["git_dir"])


@when("o dono arquiva o sistema")
def arquiva():
    from appaiforge.provisioning import archive_system

    archive_system(_ctx["system"])


@then("o repositório git do sistema é preservado")
def repo_preservado():
    assert os.path.isfile(os.path.join(DockerGitBackend().git_dir(_ctx["system"]), "HEAD"))
