"""Manifesto de conexões gravado a cada checkpoint (change add-deploy-only-system, tarefa 6.1)."""

import json
import os

import pytest

pytestmark = [pytest.mark.integration]


def _write(system, name: str, content: str) -> None:
    from appaiforge.checkpoints import workspace_dir

    path = os.path.join(workspace_dir(system), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _add_connection(system, alias: str, kind: str, active: bool = True) -> None:
    """Conexão do catálogo autorizada para o sistema (change add-db-manager-role); o alias é o que
    vai ao manifesto, e o nome no catálogo nunca aparece nele."""
    from appaiforge.db import session_scope
    from appaiforge.models import DbConnection, DbConnectionGrant

    with session_scope() as s:
        conn = DbConnection(name=f"Catálogo {alias} {system.slug}", kind=kind, host="db.interno", port=5432,
                            database="base_secreta", username="usuario_secreto", password_encrypted="cifrado")
        s.add(conn)
        s.flush()
        s.add(DbConnectionGrant(connection_id=conn.id, system_id=system.id, max_mode="read_write",
                                mode="read_write", active=active, alias=alias if active else None,
                                alias_key=alias.upper() if active else None))


@pytest.fixture()
def owner(docker_env, clean_db, monkeypatch):
    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.models import UserType

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    get_settings.cache_clear()
    return auth.create_user("manifesto@t.local", "pw", UserType.editor.value)


def test_manifesto_acompanha_checkpoint_sem_credencial(owner, git_ssh_server):
    from appaiforge import checkpoints, git_sync
    from appaiforge.services import git_remote
    from appaiforge.services.systems import create_system

    system = create_system(owner, "Homolog", f"man-{os.urandom(3).hex()}")
    _write(system, "app/main.py", "print('v1')\n")
    checkpoints.record_checkpoint(system, None, "v1", owner)
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    git_ssh_server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    git_sync.activate(system, owner)

    _add_connection(system, "vendas", "postgres")
    _add_connection(system, "estoque", "mysql")
    _write(system, ".aidb/manifest.json", '{"version": 1, "connections": [{"name": "inventada", "kind": "x"}]}')
    _write(system, "app/main.py", "print('v2')\n")
    checkpoints.record_checkpoint(system, None, "v2", owner)
    raw = checkpoints._git(system, "show", "HEAD:.aidb/manifest.json")
    assert json.loads(raw) == {"version": 1, "connections": [
        {"name": "estoque", "kind": "mysql"}, {"name": "vendas", "kind": "postgres"}]}
    for secret in ("db.interno", "5432", "base_secreta", "usuario_secreto", "cifrado", "Catálogo"):
        assert secret not in raw

    _add_connection(system, "financeiro", "bigquery")
    _add_connection(system, "nao-ativada", "postgres", active=False)
    _write(system, "app/main.py", "print('v3')\n")
    checkpoints.record_checkpoint(system, None, "v3", owner)
    names = [c["name"] for c in json.loads(checkpoints._git(system, "show", "HEAD:.aidb/manifest.json"))["connections"]]
    assert names == ["estoque", "financeiro", "vendas"]  # autorizada e não ativada fica de fora


def test_sistema_sem_repositorio_nao_grava_manifesto(owner):
    from appaiforge import checkpoints
    from appaiforge.services.systems import create_system

    system = create_system(owner, "Sem remoto", f"semrem-{os.urandom(3).hex()}")
    _add_connection(system, "vendas", "postgres")
    _write(system, "app/main.py", "print('v1')\n")
    checkpoints.record_checkpoint(system, None, "v1", owner)
    assert not os.path.exists(os.path.join(checkpoints.workspace_dir(system), ".aidb", "manifest.json"))
