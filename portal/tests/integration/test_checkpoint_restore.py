"""Rollback que preserva o histórico (change `isolate-workspace-repository`, design D5; spec
agent-harness, requirement "Checkpoints git por execução"). Driver Docker; o mesmo roteiro nos
dois drivers está em `test_driver_parity.py`."""

import os

import pytest

pytestmark = [pytest.mark.integration]


def _write(ws: str, name: str, content: str) -> None:
    path = os.path.join(ws, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _read(ws: str, name: str) -> str:
    with open(os.path.join(ws, name)) as f:
        return f.read()


@pytest.fixture()
def three_checkpoints(docker_env, clean_db):
    """Sistema com três checkpoints: v1 (app.txt), v2 (app.txt + extra.txt), v3 (app.txt)."""
    from appaiforge import auth, checkpoints
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("restore@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Restore", f"restore-{os.urandom(3).hex()}")
    ws = checkpoints.workspace_dir(system)
    cps = []
    _write(ws, "app.txt", "v1\n")
    cps.append(checkpoints.record_checkpoint(system, None, "v1", editor))
    _write(ws, "app.txt", "v2\n")
    _write(ws, "extra.txt", "só no v2\n")
    cps.append(checkpoints.record_checkpoint(system, None, "v2", editor))
    _write(ws, "app.txt", "v3\n")
    os.remove(os.path.join(ws, "extra.txt"))
    cps.append(checkpoints.record_checkpoint(system, None, "v3", editor))
    assert all(cps)
    return system, ws, cps, editor


def test_restaurar_cria_checkpoint_novo_e_preserva_os_posteriores(three_checkpoints):
    from appaiforge import checkpoints

    system, ws, (v1, v2, v3), editor = three_checkpoints
    restored = checkpoints.rollback(system, v1.git_sha, editor)

    assert restored is not None
    assert restored.origin == "restore"
    assert v1.git_sha[:8] in restored.message
    assert _read(ws, "app.txt") == "v1\n"
    assert not os.path.exists(os.path.join(ws, "extra.txt"))

    # o histórico só cresce: v2 e v3 continuam ancestrais da ponta atual
    head = checkpoints._git(system, "rev-parse", "HEAD")
    assert head == restored.git_sha
    for cp in (v1, v2, v3):
        checkpoints._git(system, "merge-base", "--is-ancestor", cp.git_sha, head)
    history = checkpoints.list_checkpoints(system)
    assert [c["origin"] for c in history][:1] == ["restore"]
    assert {c["git_sha"] for c in history} >= {v1.git_sha, v2.git_sha, v3.git_sha}


def test_checkpoint_posterior_continua_restauravel(three_checkpoints):
    from appaiforge import checkpoints

    system, ws, (v1, v2, v3), editor = three_checkpoints
    checkpoints.rollback(system, v1.git_sha, editor)
    again = checkpoints.rollback(system, v2.git_sha, editor)
    assert again is not None
    assert _read(ws, "app.txt") == "v2\n"
    assert _read(ws, "extra.txt") == "só no v2\n"


def test_restaurar_o_estado_atual_nao_cria_checkpoint(three_checkpoints):
    from appaiforge import checkpoints

    system, ws, (v1, v2, v3), editor = three_checkpoints
    before = len(checkpoints.list_checkpoints(system))
    assert checkpoints.rollback(system, v3.git_sha, editor) is None
    assert len(checkpoints.list_checkpoints(system)) == before


def test_restaurar_descarta_alteracoes_sem_checkpoint(three_checkpoints):
    from appaiforge import checkpoints

    system, ws, (v1, v2, v3), editor = three_checkpoints
    _write(ws, "app.txt", "rascunho\n")
    _write(ws, "novo.txt", "não salvo\n")
    restored = checkpoints.rollback(system, v2.git_sha, editor)
    assert restored is not None
    assert _read(ws, "app.txt") == "v2\n"
    assert not os.path.exists(os.path.join(ws, "novo.txt"))
    assert checkpoints._git(system, "status", "--porcelain") == ""


def test_checkpoint_manual_registra_origem(docker_env, clean_db):
    from appaiforge import auth, checkpoints
    from appaiforge.models import UserType
    from appaiforge.services.systems import create_system

    editor = auth.create_user("manual@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Manual", f"manual-{os.urandom(3).hex()}")
    _write(checkpoints.workspace_dir(system), "a.txt", "a\n")
    cp = checkpoints.record_checkpoint(system, None, "checkpoint manual", editor, origin=checkpoints.ORIGIN_MANUAL)
    assert cp.origin == "manual"
    assert checkpoints.list_checkpoints(system)[0]["origin"] == "manual"


def test_falha_no_meio_da_restauracao_nao_recua_a_branch(three_checkpoints, monkeypatch):
    """Achado na verificação com um sistema legado (task 5.2): se a restauração falha depois de
    mexer na árvore de trabalho, a branch não pode ficar apontando para o checkpoint antigo —
    os checkpoints posteriores sumiriam da ponta."""
    from appaiforge import checkpoints
    from appaiforge.git_backend import GitError

    system, ws, (v1, v2, v3), editor = three_checkpoints
    real_git = checkpoints._git

    def failing_clean(system_, *args):
        if args[:1] == ("clean",):
            raise GitError("git clean -fdq: warning: failed to remove app/main.py: Permission denied")
        return real_git(system_, *args)

    monkeypatch.setattr(checkpoints, "_git", failing_clean)
    with pytest.raises(GitError):
        checkpoints.rollback(system, v1.git_sha, editor)
    monkeypatch.setattr(checkpoints, "_git", real_git)

    assert checkpoints._git(system, "rev-parse", "HEAD") == v3.git_sha, "a branch continua na ponta anterior"
    assert _read(ws, "app.txt") == "v3\n", "a árvore de trabalho volta ao estado anterior à tentativa"
    assert checkpoints._git(system, "status", "--porcelain") == ""
    assert len(checkpoints.list_checkpoints(system)) == 3, "nenhum checkpoint de restauração registrado"
