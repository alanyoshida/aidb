"""Unitários de gestão de usuários/grupos e histórico desacoplado (tasks 4.x, 5.1)."""

import pytest

from appaiforge import auth
from appaiforge.db import session_scope
from appaiforge.models import AgentRun, Checkpoint, System, UserType
from appaiforge.services import audit, directory
from appaiforge.services.systems import create_system, get_system


@pytest.fixture()
def admin(clean_db):
    return auth.create_user("boss@adm.local", "pw", UserType.admin.value)


def _user_types() -> dict:
    return {e: t for e, t, _ in directory.list_users()}


def test_update_user_type_audita(admin):
    u = auth.create_user("u1@adm.local", "pw", UserType.editor.value)
    directory.update_user_type(u.email, "app_user", admin)
    assert _user_types()["u1@adm.local"] == "app_user"
    entries = audit.list_global(action="user.type")
    assert entries and entries[0]["details"] == {"old": "editor", "new": "app_user"}
    assert entries[0]["actor_email"] == admin.email


def test_set_user_active_audita(admin):
    u = auth.create_user("u2@adm.local", "pw", UserType.editor.value)
    directory.set_user_active(u.email, False, admin)
    assert {e: a for e, _, a in directory.list_users()}["u2@adm.local"] is False
    assert audit.list_global(action="user.active")


def test_update_user_type_sem_permissao(admin):
    u = auth.create_user("u3@adm.local", "pw", UserType.editor.value)
    editor = auth.create_user("ed@adm.local", "pw", UserType.editor.value)
    with pytest.raises(PermissionError):
        directory.update_user_type(u.email, "app_user", editor)


def test_delete_user_transfere_posse_e_preserva_historico(admin):
    owner = auth.create_user("owner@adm.local", "pw", UserType.editor.value)
    system = create_system(owner, "S", "adm-del")
    with session_scope() as s:
        run = AgentRun(system_id=system.id, user_id=owner.id, user_email=owner.email, prompt="p")
        s.add(run)
        s.flush()
        s.add(Checkpoint(system_id=system.id, git_sha="abc123", message="m",
                         author_id=owner.id, author_email=owner.email))

    directory.delete_user(owner.email, admin)

    assert get_system(system.id).owner_id == admin.id
    assert "owner@adm.local" not in _user_types()
    with session_scope() as s:
        cp = s.query(Checkpoint).filter_by(system_id=system.id).one()
        run = s.query(AgentRun).filter_by(system_id=system.id).one()
        assert cp.author_id is None and cp.author_email == "owner@adm.local"
        assert run.user_id is None and run.user_email == "owner@adm.local"
    entry = audit.list_global(action="user.delete")[0]
    assert entry["actor_email"] == admin.email
    assert system.id in entry["details"]["transferred_system_ids"]


def test_delete_user_sem_permissao(admin):
    u = auth.create_user("u4@adm.local", "pw", UserType.editor.value)
    editor = auth.create_user("ed2@adm.local", "pw", UserType.editor.value)
    with pytest.raises(PermissionError):
        directory.delete_user(u.email, editor)


def test_group_ops_auditam(admin):
    owner = auth.create_user("gowner@adm.local", "pw", UserType.editor.value)
    system = create_system(owner, "G", "adm-grp")
    member = auth.create_user("m@adm.local", "pw", UserType.app_user.value)

    directory.create_group("equipe", actor=admin)
    directory.add_member("equipe", member.email, actor=admin)
    directory.link_group_to_system("equipe", system.slug, actor=admin)
    directory.rename_group("equipe", "equipe-2", admin)

    assert {n: (e, s) for n, e, s in directory.list_groups()}["equipe-2"] == ([member.email], [system.slug])
    directory.remove_member("equipe-2", member.email, admin)
    directory.unlink_group_from_system("equipe-2", system.slug, admin)
    assert directory.list_groups()[0][1] == [] and directory.list_groups()[0][2] == []

    directory.delete_group("equipe-2", admin)
    assert directory.list_groups() == []

    actions = {e["action"] for e in audit.list_global()}
    assert {"group.create", "group.member_add", "group.link", "group.rename",
            "group.member_remove", "group.unlink", "group.delete"} <= actions


def test_rename_group_nome_duplicado(admin):
    directory.create_group("a", actor=admin)
    directory.create_group("b", actor=admin)
    with pytest.raises(directory.NameTaken):
        directory.rename_group("b", "a", admin)