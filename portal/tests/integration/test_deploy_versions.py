"""Versões, verificação e implantação de sistemas só implantação (change add-deploy-only-system,
tarefas 3.1–3.3 e 4.1–4.4), contra o servidor git por SSH da fixture e um container Docker real.

O portal dos testes roda fora da rede Docker, então a sonda de saúde do driver é trocada por uma
que pergunta à própria app, de dentro do container — a app servida é a real."""

import json
import os

import pytest

pytestmark = [pytest.mark.integration]

APP = """import os
from http.server import BaseHTTPRequestHandler, HTTPServer
{extra}

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{marker}")

    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", int(os.environ["PORT"])), H).serve_forever()
"""

PYPROJECT = '[project]\nname = "app"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = []\n'
LOCK = ('version = 1\nrequires-python = ">=3.9"\n\n[[package]]\nname = "app"\nversion = "0.1.0"\n'
        'source = { virtual = "." }\n')
BROKEN_PYPROJECT = PYPROJECT.replace("dependencies = []", 'dependencies = ["pacote-inexistente-aidb"]')
BROKEN_LOCK = LOCK + (
    'dependencies = [\n    { name = "pacote-inexistente-aidb" },\n]\n\n[package.metadata]\n'
    'requires-dist = [{ name = "pacote-inexistente-aidb" }]\n\n[[package]]\nname = "pacote-inexistente-aidb"\n'
    'version = "9.9.9"\nsource = { registry = "https://pypi.org/simple" }\n'
    'wheels = [\n    { url = "https://files.pythonhosted.org/packages/00/00/pacote_inexistente_aidb-9.9.9-py3-none-any.whl",'
    ' hash = "sha256:' + "0" * 64 + '", size = 1 },\n]\n'
)


def app_files(marker: str, *, lock: str = LOCK, pyproject: str = PYPROJECT, extra: str = "") -> dict[str, str]:
    return {"app/main.py": APP.format(marker=marker, extra=extra), "app/pyproject.toml": pyproject, "app/uv.lock": lock}


def _probe(system) -> str:
    from appaiforge.drivers import get_driver

    code, out, _ = get_driver().exec_in_app(
        system, ["python3", "-c", "import urllib.request as u;"
                 "print(u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:8080/').read().decode())"],
        timeout=10,
    )
    return out.strip() if code == 0 else ""


@pytest.fixture()
def prod(docker_env, clean_db, git_ssh_server, monkeypatch):
    """Sistema só implantação provisionado, ligado ao repositório da fixture com a chave do
    sistema autorizada e a identidade do servidor confirmada."""
    from appaiforge import auth, git_sync
    from appaiforge.config import get_settings
    from appaiforge.drivers.docker_driver import DockerProvisioningDriver
    from appaiforge.models import SystemStatus, UserType
    from appaiforge.provisioning import provision_system
    from appaiforge.services import catalog, git_remote
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system, set_status
    from conftest import remove_system_containers

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    monkeypatch.setenv("APPAIFORGE_DEPLOY_HEALTH_TIMEOUT", "25")
    monkeypatch.setenv("APPAIFORGE_DEPLOY_HEALTH_INTERVAL", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(DockerProvisioningDriver, "is_healthy", lambda self, slug: bool(_probe(state["system"])))
    state = {}
    catalog.ensure_presets()
    owner = auth.create_user("prod@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Produção", f"prod-{os.urandom(3).hex()}", kind=KIND_DEPLOY_ONLY)
    state["system"] = system
    provision_system(system)
    set_status(system.id, SystemStatus.active, "")
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    git_ssh_server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    git_ssh_server.init_repo()
    try:
        yield system, owner
    finally:
        remove_system_containers(system.slug)


def release(server, tag: str, files: dict[str, str], branch: str = "main") -> str:
    sha = server.commit_as_human(branch, files, f"versão {tag}")
    server.git("tag", tag, sha)
    return sha


def remote_refs(server) -> str:
    return server.git("for-each-ref", "--format=%(refname) %(objectname)")


def test_lista_versoes_em_ordem_e_nada_e_escrito_no_remoto(prod, git_ssh_server):
    from appaiforge import deploy

    system, owner = prod
    base = release(git_ssh_server, "v1.0.1", app_files("V101"))
    git_ssh_server.git("tag", "v1.0.10", base)
    git_ssh_server.exec("git", "-c", "user.name=ci", "-c", "user.email=ci@remoto", "--git-dir", "/srv/git/time/app.git", "tag", "-a", "-m", "anotada", "v1.0.2", base)
    git_ssh_server.git("tag", "rascunho", base)
    before = remote_refs(git_ssh_server)

    versions = deploy.list_versions(system)
    assert [v["tag"] for v in versions] == ["v1.0.10", "v1.0.2", "v1.0.1"]
    assert all(v["sha"] == base for v in versions), "tag anotada resolvida para o commit"
    result = deploy.deploy(system, "v1.0.2", actor=owner)
    assert result["status"] == "succeeded", result["detail"]
    versions = deploy.list_versions(system)
    assert [(v["tag"], v["current"], v["deployed"]) for v in versions] == [
        ("v1.0.10", False, False), ("v1.0.2", True, True), ("v1.0.1", False, False)]
    assert remote_refs(git_ssh_server) == before, "nenhuma ref remota muda"


def test_tag_na_branch_implantada_e_fora_recusada(prod, git_ssh_server):
    from appaiforge import deploy
    from appaiforge.checkpoints import workspace_dir

    system, owner = prod
    v1 = release(git_ssh_server, "v1.0.0", app_files("VERSAO-1"))
    result = deploy.deploy(system, "v1.0.0", actor=owner)
    assert result["status"] == "succeeded", result["detail"]
    assert result["commit_sha"] == v1 and result["trigger"] == "manual"
    assert _probe(system) == "VERSAO-1"

    git_ssh_server.git("branch", "experimento", "main")
    release(git_ssh_server, "v9.0.0", app_files("FORA"), branch="experimento")
    refused = deploy.deploy(system, "v9.0.0", actor=owner)
    assert refused["status"] == "failed" and "não passou pela branch de destino" in refused["detail"]
    with open(os.path.join(workspace_dir(system), "app", "main.py")) as f:
        assert "VERSAO-1" in f.read(), "nada muda no workspace"
    assert deploy.current_deployment(system.id)["tag"] == "v1.0.0"


def test_tag_movida_registra_o_commit_verificado(prod, git_ssh_server):
    from appaiforge import deploy

    system, owner = prod
    release(git_ssh_server, "v1.0.0", app_files("VERSAO-1"))
    assert [v["tag"] for v in deploy.list_versions(system)] == ["v1.0.0"]
    moved = git_ssh_server.commit_as_human("main", app_files("MOVIDA"), "nova ponta")
    git_ssh_server.git("tag", "-f", "v1.0.0", moved)
    result = deploy.deploy(system, "v1.0.0", actor=owner)
    assert result["status"] == "succeeded" and result["commit_sha"] == moved
    assert _probe(system) == "MOVIDA"


def test_lock_igual_nao_reinstala_e_dependencia_que_falha_mantem_a_versao(prod, git_ssh_server, monkeypatch):
    from appaiforge import deploy
    from appaiforge.drivers.docker_driver import DockerProvisioningDriver

    system, owner = prod
    syncs = []
    original = DockerProvisioningDriver.exec_in_app

    def spy(self, sys, command, **kwargs):
        if command[:2] == ["uv", "sync"]:
            syncs.append(command)
        return original(self, sys, command, **kwargs)

    monkeypatch.setattr(DockerProvisioningDriver, "exec_in_app", spy)
    release(git_ssh_server, "v1.0.0", app_files("VERSAO-1"))
    assert deploy.deploy(system, "v1.0.0", actor=owner)["status"] == "succeeded"
    assert len(syncs) == 1, "primeira versão instala o ambiente"
    release(git_ssh_server, "v1.1.0", app_files("VERSAO-1-1"))
    assert deploy.deploy(system, "v1.1.0", actor=owner)["status"] == "succeeded"
    assert len(syncs) == 1, "lock igual não reinstala"
    assert _probe(system) == "VERSAO-1-1"

    release(git_ssh_server, "v1.2.0", app_files("QUEBRADA", lock=BROKEN_LOCK, pyproject=BROKEN_PYPROJECT))
    failed = deploy.deploy(system, "v1.2.0", actor=owner)
    assert len(syncs) == 2
    assert failed["status"] == "failed" and "dependências" in failed["detail"], failed
    assert _probe(system) == "VERSAO-1-1", "a versão anterior continua servida"
    assert deploy.current_deployment(system.id)["tag"] == "v1.1.0"


def test_versao_que_nao_sobe_volta_para_a_anterior(prod, git_ssh_server):
    from appaiforge import deploy

    system, owner = prod
    v1 = release(git_ssh_server, "v1.0.0", app_files("VERSAO-1"))
    assert deploy.deploy(system, "v1.0.0", actor=owner)["status"] == "succeeded"
    release(git_ssh_server, "v2.0.0", app_files("NUNCA", extra="raise SystemExit('quebrou ao subir')"))
    result = deploy.deploy(system, "v2.0.0", actor=owner)
    assert result["status"] == "rolled_back", result
    assert "não ficou saudável" in result["detail"] and v1[:8] in result["detail"]
    assert _probe(system) == "VERSAO-1"
    assert deploy.current_deployment(system.id)["tag"] == "v1.0.0"


def test_manifesto_confere_as_conexoes(prod, git_ssh_server):
    from appaiforge import deploy
    from appaiforge.db import session_scope
    from appaiforge.models import DbConnection

    system, owner = prod
    manifest = json.dumps({"version": 1, "connections": [{"name": "vendas", "kind": "postgres"}]})
    release(git_ssh_server, "v1.0.0", {**app_files("SEM-MANIFESTO")})
    no_manifest = deploy.deploy(system, "v1.0.0", actor=owner)
    assert no_manifest["status"] == "succeeded" and "não tem manifesto" in no_manifest["detail"]

    release(git_ssh_server, "v1.1.0", {**app_files("COM-MANIFESTO"), ".aidb/manifest.json": manifest})
    missing = deploy.deploy(system, "v1.1.0", actor=owner)
    assert missing["status"] == "failed" and "vendas" in missing["detail"]
    assert _probe(system) == "SEM-MANIFESTO"

    with session_scope() as s:
        s.add(DbConnection(system_id=system.id, name="vendas", kind="postgres", host="db", port=5432,
                           database="vendas", username="u", password_encrypted="x"))
    complete = deploy.deploy(system, "v1.1.0", actor=owner)
    assert complete["status"] == "succeeded" and complete["detail"] == ""


def test_uma_implantacao_por_vez_e_recuperacao_da_interrompida(prod, git_ssh_server):
    from appaiforge import deploy, git_sync
    from appaiforge.db import session_scope
    from appaiforge.git_backend import get_backend
    from appaiforge.models import Deployment

    system, owner = prod
    v1 = release(git_ssh_server, "v1.0.0", app_files("VERSAO-1"))
    assert deploy.deploy(system, "v1.0.0", actor=owner)["status"] == "succeeded"
    v2 = release(git_ssh_server, "v2.0.0", app_files("VERSAO-2"))

    lock = git_sync.system_lock(system.id)
    lock.acquire()
    try:
        with pytest.raises(deploy.DeployBusy):
            deploy.deploy(system, "v2.0.0", actor=owner)
    finally:
        lock.release()

    # Interrompida no meio: código trocado, registro ainda `running`.
    deploy.verify_and_fetch(system, "v2.0.0")
    deploy._checkout(system, v2)
    with session_scope() as s:
        s.add(Deployment(system_id=system.id, tag="v2.0.0", commit_sha=v2, trigger="manual", status="running"))
    deploy.recover_interrupted()
    history = deploy.list_deployments(system.id)
    assert history[0]["tag"] == "v2.0.0" and history[0]["status"] == "failed"
    assert "interrompida" in history[0]["detail"]
    assert get_backend().run(system, "rev-parse", "HEAD", work_tree=False) == v1


def test_consulta_periodica_implanta_a_tag_nova_sozinha(prod, git_ssh_server):
    import threading
    import time

    from appaiforge import deploy
    from appaiforge.db import session_scope
    from appaiforge.models import DeploySettings

    system, owner = prod
    with session_scope() as s:
        row = s.get(DeploySettings, system.id)
        row.mode, row.detection = "automatic", "polling"
    stop = threading.Event()
    deploy.start_poller(interval=1, stop=stop)
    try:
        release(git_ssh_server, "v1.0.0", app_files("AUTOMATICA"))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            current = deploy.current_deployment(system.id)
            if current:
                break
            time.sleep(1)
        assert current and current["tag"] == "v1.0.0" and current["trigger"] == "polling"
        assert current["actor_id"] is None
        assert _probe(system) == "AUTOMATICA"
    finally:
        stop.set()
        while any(t.name == "deploy-poller" and t.is_alive() for t in threading.enumerate()):
            time.sleep(0.5)
