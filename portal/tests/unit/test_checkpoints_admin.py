"""Unitários de exclusão de checkpoint (task 6.1)."""

from appaiforge import auth, checkpoints
from appaiforge.db import session_scope
from appaiforge.models import Checkpoint, UserType
from appaiforge.services import audit
from appaiforge.services.systems import create_system


def test_delete_checkpoint_remove_e_audita(clean_db):
    editor = auth.create_user("cp@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "CP", "cp-del")
    with session_scope() as s:
        cp = Checkpoint(system_id=system.id, git_sha="deadbeef", message="m",
                        author_id=editor.id, author_email=editor.email)
        s.add(cp)
        s.flush()
        checkpoint_id = cp.id

    checkpoints.delete_checkpoint(system, checkpoint_id, actor=editor)

    with session_scope() as s:
        assert s.get(Checkpoint, checkpoint_id) is None
    entries = audit.list_global(action="checkpoint.delete")
    assert entries and entries[0]["resource_id"] == checkpoint_id