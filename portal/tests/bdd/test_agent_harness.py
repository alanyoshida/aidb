"""Steps BDD de agent-harness: requirement "Checkpoints git por execução" (driver Docker)."""

import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth, checkpoints

scenarios("features/agent_harness.feature")

_ctx: dict = {}


@pytest.fixture()
def ws_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path / "gitdirs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "docker")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    _ctx.clear()


def _app(content: str | None = None) -> str | None:
    path = os.path.join(_ctx["ws"], "app", "main.py")
    if content is None:
        with open(path) as f:
            return f.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return None


def _new_system():
    from appaiforge.services.systems import create_system

    editor = auth.create_user(f"ah-{os.urandom(3).hex()}@bdd.local", "pw", "editor")
    system = create_system(editor, "AH", f"ah-{os.urandom(3).hex()}")
    _ctx.update(editor=editor, system=system, ws=checkpoints.workspace_dir(system), cps={})


@given("um sistema sem checkpoints")
def sistema_sem_checkpoints(ws_env, clean_db):
    _new_system()


@given(parsers.parse('um sistema com os checkpoints "{a}", "{b}" e "{c}"'))
def sistema_com_checkpoints(ws_env, clean_db, a, b, c):
    _new_system()
    for name in (a, b, c):
        _app(f"print('{name}')\n")
        _ctx["cps"][name] = checkpoints.record_checkpoint(_ctx["system"], None, name, _ctx["editor"])


@when("uma execução do agente termina com sucesso alterando a app")
def execucao_com_sucesso():
    _app("print('gerado')\n")
    checkpoints.record_checkpoint(_ctx["system"], None, "crie o painel de clientes", _ctx["editor"])


@then("um checkpoint com a descrição da alteração aparece no histórico do sistema")
def checkpoint_no_historico():
    history = checkpoints.list_checkpoints(_ctx["system"])
    assert [c["message"] for c in history] == ["crie o painel de clientes"]
    assert history[0]["origin"] == "run"


@when(parsers.parse('o dono restaura o checkpoint "{name}"'))
def restaura(name):
    _ctx["before"] = len(checkpoints.list_checkpoints(_ctx["system"]))
    _ctx["restored"] = checkpoints.rollback(_ctx["system"], _ctx["cps"][name].git_sha, _ctx["editor"])


@then(parsers.parse('o workspace volta ao estado do checkpoint "{name}"'))
def estado_do_checkpoint(name):
    assert _app() == f"print('{name}')\n"


@then(parsers.parse('os checkpoints "{a}" e "{b}" continuam no histórico'))
def posteriores_no_historico(a, b):
    shas = {c["git_sha"] for c in checkpoints.list_checkpoints(_ctx["system"])}
    assert {_ctx["cps"][a].git_sha, _ctx["cps"][b].git_sha} <= shas


@then(parsers.parse('o checkpoint "{name}" continua restaurável'))
def continua_restauravel(name):
    assert checkpoints.rollback(_ctx["system"], _ctx["cps"][name].git_sha, _ctx["editor"]) is not None
    assert _app() == f"print('{name}')\n"


@then(parsers.parse('aparece no histórico um checkpoint de restauração que identifica "{name}"'))
def checkpoint_de_restauracao(name):
    newest = checkpoints.list_checkpoints(_ctx["system"])[0]
    assert newest["origin"] == "restore"
    assert _ctx["cps"][name].git_sha[:8] in newest["message"]


@then("o portal informa que não havia nada a restaurar")
def nada_a_restaurar():
    assert _ctx["restored"] is None


@then("nenhum checkpoint novo é criado")
def nenhum_checkpoint_novo():
    assert len(checkpoints.list_checkpoints(_ctx["system"])) == _ctx["before"]
