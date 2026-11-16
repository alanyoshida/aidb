"""Paridade observável entre os drivers de provisionamento (change `add-kubernetes-driver`,
requirement "Paridade observável entre drivers de provisionamento", capability
`container-driver-kubernetes`): o mesmo cenário, exercitado só através da interface comum
(`provisioning.py` + `get_driver()`), produz o mesmo resultado observável nos dois drivers —
sem nenhuma chamada direta ao SDK do Docker ou ao client do Kubernetes neste arquivo."""

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


def _setup_env(driver: str, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", driver)
    if driver == "kubernetes":
        monkeypatch.setenv("APPAIFORGE_K8S_NAMESPACE", "appaiforge-test")
    from appaiforge.config import get_settings

    get_settings.cache_clear()


def _cleanup(driver: str, system) -> None:
    from appaiforge.provisioning import stop_and_remove, unpublish_app

    unpublish_app(system.slug)
    stop_and_remove(system)
    if driver == "kubernetes":
        # Service/IngressRoute/Middleware não são tocados por `stop_and_remove` (ver
        # DockerProvisioningDriver.remove e KubernetesProvisioningDriver.remove) — `unpublish_app`
        # acima já cuida deles pelos dois drivers. O PVC do workspace também não é tocado por
        # `remove()` — deliberado em produção (preserva o workspace ao arquivar), mas este é um
        # teste descartável: sem limpar aqui, cada rodada acumula um PVC órfão no cluster.
        from kubernetes import client as k8s
        from kubernetes.client.rest import ApiException

        from appaiforge.config import get_settings
        from appaiforge.drivers.kubernetes_driver import _workspace_pvc_name

        try:
            k8s.CoreV1Api().delete_namespaced_persistent_volume_claim(
                _workspace_pvc_name(system.slug), get_settings().k8s_namespace
            )
        except ApiException as exc:
            if exc.status != 404:
                raise


def _read_workspace_file(driver: str, system, rel_path: str) -> str:
    """Lê um arquivo do workspace REAL do sistema — só esta função conhece a diferença entre
    drivers (bind mount local do driver Docker vs. exec dentro do Pod do driver Kubernetes); o
    resto do teste fica agnóstico de driver, como o resto deste arquivo (change
    `fix-k8s-workspace-materialize-delete`)."""
    if driver == "kubernetes":
        import subprocess

        from appaiforge.edge import system_container_name

        result = subprocess.run(
            [
                "kubectl", "--context", "kind-appaiforge-dev", "-n", "appaiforge-test",
                "exec", system_container_name(system.slug), "-c", "agent", "--",
                "cat", f"/workspace/{rel_path}",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        return result.stdout

    from appaiforge.config import get_settings

    with open(os.path.join(get_settings().workspaces_dir, system.slug, rel_path)) as f:
        return f.read()


def _workspace_storage_exists(driver: str, system) -> bool:
    """Existência do armazenamento REAL do workspace (PVC no driver Kubernetes, diretório local
    no driver Docker) — não do caminho local `workspaces_dir`, que sob o driver Kubernetes nunca
    foi o workspace de verdade (achado da change `fix-k8s-workspace-materialize-delete`)."""
    if driver == "kubernetes":
        from kubernetes import client as k8s
        from kubernetes.client.rest import ApiException

        from appaiforge.config import get_settings
        from appaiforge.drivers.kubernetes_driver import _workspace_pvc_name

        try:
            k8s.CoreV1Api().read_namespaced_persistent_volume_claim(
                _workspace_pvc_name(system.slug), get_settings().k8s_namespace
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    from appaiforge.config import get_settings

    return os.path.isdir(os.path.join(get_settings().workspaces_dir, system.slug))


@pytest.mark.parametrize("driver", DRIVERS)
def test_paridade_materialize_e_exclusao_definitiva(driver, tmp_path, monkeypatch, clean_db):
    """Change `fix-k8s-workspace-materialize-delete`: antes desta change, sob o driver
    Kubernetes, `materialize()` escrevia num diretório local inerte — AGENTS.md nunca chegava ao
    agente — e `delete_system()` nunca removia a PVC real do workspace, deixando-a órfã no
    cluster. Mesmo roteiro, mesma asserção, que já passava no driver Docker (bind mount) e
    falhava silenciosamente no Kubernetes antes deste fix."""
    _setup_env(driver, tmp_path, monkeypatch)

    from appaiforge import auth, guidelines
    from appaiforge.models import UserType
    from appaiforge.provisioning import delete_system, provision_system
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    catalog.ensure_presets()
    editor = auth.create_user(f"parity-mat-{driver}@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "ParidadeMat", f"parity-mat-{driver}-{os.urandom(3).hex()}")

    try:
        provision_system(system)

        # 1. guidelines chegam ao workspace REAL do sistema, nos dois drivers (materialize()
        # já espera a prontidão do container internamente sob o driver Kubernetes)
        guidelines.materialize(system)
        assert _read_workspace_file(driver, system, "AGENTS.md") == guidelines.current_content()
        assert _workspace_storage_exists(driver, system)

        # 2. exclusão definitiva remove o armazenamento real do workspace, nos dois drivers
        delete_system(system)
        assert not _workspace_storage_exists(driver, system)
    finally:
        _cleanup(driver, system)


@pytest.mark.parametrize("driver", DRIVERS)
def test_paridade_provisionar_publicar_e_reconciliar(driver, tmp_path, monkeypatch, clean_db):
    """Mesmo roteiro, mesma asserção, driver trocado só pela configuração: provisiona, publica,
    confirma reconciliação depois de remover a unidade de execução — tudo via `provisioning.py`,
    nunca via SDK específico de driver."""
    _setup_env(driver, tmp_path, monkeypatch)

    from appaiforge import auth
    from appaiforge.drivers import get_driver
    from appaiforge.models import SystemStatus, UserType
    from appaiforge.provisioning import provision_system, reconcile
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system, set_status
    from appaiforge.edge import publish_app

    catalog.ensure_presets()
    editor = auth.create_user(f"parity-{driver}@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Paridade", f"parity-{driver}-{os.urandom(3).hex()}")

    try:
        # 1. provisionar: o id devolvido não é vazio, qualquer que seja o driver
        container_id = provision_system(system)
        assert container_id

        # 2. publicar: não levanta erro nenhum nos dois drivers
        publish_app(system)

        # 3. reconciliação encontra a unidade presente sem recriar nada
        set_status(system.id, SystemStatus.active, "")
        driver_obj = get_driver()
        driver_obj.reconcile_one(system.id, system.slug)  # não levanta ComputeUnitNotFound

        # 4. unidade removida por fora -> reconcile() detecta e recria, nos dois drivers
        driver_obj.remove(system)
        reconcile()
        driver_obj.reconcile_one(system.id, system.slug)  # existe de novo, não levanta
    finally:
        _cleanup(driver, system)
