"""O checkpoint git da execução inclui os artefatos do OpenSpec (change
add-openspec-to-system-container, D4; spec system-openspec — "Checkpoint inclui os artefatos")."""

import os
import subprocess

from appaiforge import auth, checkpoints
from appaiforge.models import UserType
from appaiforge.services.systems import create_system


def test_checkpoint_inclui_openspec_e_comandos_do_agente(clean_db, tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    editor = auth.create_user("ospec-cp@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "OS", "ospec-cp")
    ws = checkpoints.workspace_dir(system)
    for rel, content in {
        "openspec/config.yaml": "schema: spec-driven\n",
        "openspec/changes/filtro-por-data/proposal.md": "# Proposta\n",
        ".opencode/commands/opsx-propose.md": "---\ndescription: x\n---\n",
        "app/main.py": "print('ok')\n",
    }.items():
        os.makedirs(os.path.dirname(os.path.join(ws, rel)), exist_ok=True)
        with open(os.path.join(ws, rel), "w") as f:
            f.write(content)

    cp = checkpoints.record_checkpoint(system, None, "change criada pelo /opsx-propose", editor)
    assert cp is not None
    tracked = subprocess.run(["git", "-C", ws, "ls-tree", "-r", "--name-only", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.split()
    assert "openspec/changes/filtro-por-data/proposal.md" in tracked
    assert ".opencode/commands/opsx-propose.md" in tracked
