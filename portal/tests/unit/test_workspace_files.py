"""Unitários do serviço de arquivos do workspace (tasks 1.1/1.2/1.3,
capability workspace-viewer)."""

import os

import pytest

from appaiforge import auth, workspace_files
from appaiforge.models import UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def system(fake_workspace, clean_db):
    editor = auth.create_user("wf@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Workspace Files", "wf-sys")


def _write(system, rel_path: str, content: bytes) -> None:
    full = os.path.join(workspace_files.project_dir(system), rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(content)


def test_project_dir_eh_app_dentro_do_workspace(system):
    from appaiforge.checkpoints import workspace_dir

    assert workspace_files.project_dir(system) == os.path.join(workspace_dir(system), "app")


def test_list_tree_devolve_vazio_quando_app_nao_existe(system):
    assert workspace_files.list_tree(system) == []


def test_list_tree_reflete_estrutura_real(system):
    _write(system, "main.py", b"print('oi')\n")
    _write(system, "templates/base.html", b"<html></html>")

    tree = workspace_files.list_tree(system)
    labels = {n["label"] for n in tree}
    assert labels == {"main.py", "templates"}

    templates_node = next(n for n in tree if n["label"] == "templates")
    assert templates_node["icon"] == workspace_files.FOLDER_ICON
    assert templates_node["children"][0]["label"] == "base.html"
    assert templates_node["children"][0]["id"] == os.path.join("templates", "base.html")

    main_node = next(n for n in tree if n["label"] == "main.py")
    assert main_node["icon"] == "code"


def test_list_tree_omite_diretorios_tecnicos(system):
    _write(system, "main.py", b"print('oi')\n")
    _write(system, ".venv/lib/x.py", b"x = 1\n")
    _write(system, "__pycache__/main.cpython-312.pyc", b"\x00\x01")
    _write(system, ".git/HEAD", b"ref: refs/heads/main\n")

    tree = workspace_files.list_tree(system)
    labels = {n["label"] for n in tree}
    assert labels == {"main.py"}


def test_read_file_texto_normal(system):
    _write(system, "main.py", b"print('ola')\n")
    content = workspace_files.read_file(system, "main.py")
    assert content.binary is False
    assert content.text == "print('ola')\n"
    assert content.language == "Python"


def test_read_file_binario_devolve_marcador_sem_lancar(system):
    _write(system, "dados.bin", b"\x80\x81\x82\xff\xfe")
    content = workspace_files.read_file(system, "dados.bin")
    assert content.binary is True
    assert content.text is None


def test_read_file_recusa_escapar_do_projeto(system):
    _write(system, "main.py", b"print('oi')\n")
    with pytest.raises(ValueError):
        workspace_files.read_file(system, "../../etc/passwd")


def test_language_for_mapeia_extensoes_conhecidas():
    assert workspace_files.language_for("main.py") == "Python"
    assert workspace_files.language_for("pyproject.toml") == "TOML"
    assert workspace_files.language_for("uv.lock") == "TOML"


def test_language_for_extensao_desconhecida_devolve_none():
    assert workspace_files.language_for("README.XYZ") is None
    assert workspace_files.language_for("Dockerfile") is None


def test_icon_for_mapeia_categorias_conhecidas():
    assert workspace_files.icon_for("main.py") == "code"
    assert workspace_files.icon_for("data.json") == "data_object"
    assert workspace_files.icon_for("pyproject.toml") == "settings"
    assert workspace_files.icon_for("README.md") == "article"


def test_icon_for_extensao_desconhecida_devolve_padrao():
    assert workspace_files.icon_for("Dockerfile") == workspace_files.DEFAULT_FILE_ICON
