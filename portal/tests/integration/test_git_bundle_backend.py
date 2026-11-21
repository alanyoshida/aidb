"""Exportar e importar pacotes git no repositório do sistema, nos dois drivers (change
add-system-git-remote, tarefa 3.3)."""

import os

import pytest

pytestmark = [pytest.mark.integration]

DRIVERS = ["docker"]
try:
    from kubernetes import config as k8s_config

    k8s_config.load_kube_config(context="kind-appaiforge-dev")
    DRIVERS.append("kubernetes")
except Exception:
    pass


@pytest.mark.parametrize("driver", DRIVERS)
def test_pacote_exportado_e_reimportado_preserva_os_commits(driver, tmp_path, monkeypatch, clean_db):
    import test_driver_parity as parity

    parity._setup_env(driver, tmp_path, monkeypatch)
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path / "gitdirs"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    from appaiforge import auth, checkpoints
    from appaiforge.git_backend import GitError, get_backend
    from appaiforge.models import UserType
    from appaiforge.provisioning import delete_system, provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    catalog.ensure_presets()
    editor = auth.create_user(f"bundle-{driver}@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Bundle", f"bundle-{driver}-{os.urandom(3).hex()}")
    try:
        provision_system(system)
        if driver == "kubernetes":
            from appaiforge.drivers.kubernetes_driver import _wait_for_agent_container_started
            from appaiforge.edge import system_container_name

            _wait_for_agent_container_started(system_container_name(system.slug), "appaiforge-test", timeout=120)
        backend = get_backend()
        parity._write_workspace_file(driver, system, "app.txt", "v1\n")
        v1 = checkpoints.record_checkpoint(system, None, "v1", editor).git_sha
        parity._write_workspace_file(driver, system, "app.txt", "v2\n")
        v2 = checkpoints.record_checkpoint(system, None, "v2", editor).git_sha

        full = backend.export_bundle(system, ["main"])
        incremental = backend.export_bundle(system, ["main", f"^{v1}"])
        assert full.startswith(b"# v2 git bundle") or full.startswith(b"# v3 git bundle")
        assert len(incremental) < len(full)

        # reimporta o pacote completo numa referência separada e confere os commits
        backend.import_bundle(system, full, "+refs/heads/main:refs/aidb/incoming")
        assert checkpoints._git(system, "rev-parse", "refs/aidb/incoming") == v2
        assert checkpoints._git(system, "rev-list", "--count", "refs/aidb/incoming") == "2"

        with pytest.raises(GitError):
            backend.import_bundle(system, b"isto nao e um pacote", "+refs/heads/main:refs/aidb/lixo")
        delete_system(system)
    finally:
        parity._cleanup(driver, system)
