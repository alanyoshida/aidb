"""Unitários da auditoria de gestão (capability management-audit, task 1.2)."""

from appaiforge import auth
from appaiforge.models import UserType
from appaiforge.services import audit
from appaiforge.services.systems import create_system


def test_record_grava_autor_acao_e_alvo(clean_db):
    admin = auth.create_user("admin-audit@t.local", "pw", UserType.admin.value)
    system = create_system(admin, "Audit", "audit-a")
    audit.record(
        actor_id=admin.id,
        actor_email=admin.email,
        action="conn.remove",
        resource_type="connection",
        resource_id="conn-1",
        system_id=system.id,
        details={"name": "vendas"},
    )
    entries = [e for e in audit.list_global() if e["action"] == "conn.remove"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["actor_id"] == admin.id
    assert entry["actor_email"] == "admin-audit@t.local"
    assert entry["action"] == "conn.remove"
    assert entry["resource_type"] == "connection"
    assert entry["resource_id"] == "conn-1"
    assert entry["details"] == {"name": "vendas"}


def test_list_global_filtra_por_recurso_e_acao(clean_db):
    admin = auth.create_user("admin-audit2@t.local", "pw", UserType.admin.value)
    audit.record(actor_id=admin.id, action="user.delete", resource_type="user", resource_id="u1")
    audit.record(actor_id=admin.id, action="group.rename", resource_type="group", resource_id="g1")
    assert len(audit.list_global(resource_type="user")) == 1
    assert audit.list_global(resource_type="user")[0]["action"] == "user.delete"
    assert len(audit.list_global(action="group.rename")) == 1


def test_list_global_filtra_por_autor(clean_db):
    a = auth.create_user("a@audit.local", "pw", UserType.admin.value)
    b = auth.create_user("b@audit.local", "pw", UserType.admin.value)
    audit.record(actor_id=a.id, actor_email=a.email, action="user.delete", resource_type="user", resource_id="u1")
    audit.record(actor_id=b.id, actor_email=b.email, action="user.delete", resource_type="user", resource_id="u2")
    only_a = audit.list_global(actor_email="a@audit.local")
    assert len(only_a) == 1 and only_a[0]["actor_id"] == a.id


def test_list_by_system_so_do_sistema(clean_db):
    admin = auth.create_user("admin-audit3@t.local", "pw", UserType.admin.value)
    s1 = create_system(admin, "S1", "audit-s1")
    s2 = create_system(admin, "S2", "audit-s2")
    audit.record(actor_id=admin.id, action="conn.update", resource_type="connection", system_id=s1.id)
    audit.record(actor_id=admin.id, action="conn.update", resource_type="connection", system_id=s2.id)
    only_s1 = [e for e in audit.list_by_system(s1.id) if e["action"] == "conn.update"]
    assert len(only_s1) == 1 and only_s1[0]["system_id"] == s1.id


def test_detalhes_nunca_guardam_segredos(clean_db):
    admin = auth.create_user("admin-audit4@t.local", "pw", UserType.admin.value)
    audit.record(
        actor_id=admin.id,
        action="conn.update",
        resource_type="connection",
        resource_id="c1",
        details={"name": "vendas", "password": "segredo", "connection_key": "abc", "host": "db"},
    )
    entry = audit.list_global()[0]
    assert "password" not in entry["details"]
    assert "connection_key" not in entry["details"]
    assert entry["details"] == {"name": "vendas", "host": "db"}
    assert "segredo" not in str(entry)