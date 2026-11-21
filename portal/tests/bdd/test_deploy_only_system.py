"""Steps BDD de deploy-only-system (change add-deploy-only-system), driver Docker, contra o servidor
git por SSH efêmero dos testes de integração. A sonda de saúde pergunta à app de dentro do
container, como em tests/integration/test_deploy_versions.py."""

import json
import os
import sys

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integration"))

from appaiforge import auth, deploy  # noqa: E402

scenarios("features/deploy_only_system.feature")

_ctx: dict = {}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for var, sub in (("APPAIFORGE_WORKSPACES_DIR", "workspaces"), ("APPAIFORGE_HOST_WORKSPACES_DIR", "workspaces"),
                     ("APPAIFORGE_GITDIRS_DIR", "gitdirs"), ("APPAIFORGE_GIT_RELAYS_DIR", "relays"),
                     ("APPAIFORGE_DYNAMIC_CONFIG_DIR", "dynamic"), ("APPAIFORGE_CONFIGS_DIR", "configs"),
                     ("APPAIFORGE_HOST_CONFIGS_DIR", "configs")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "docker")
    monkeypatch.setenv("APPAIFORGE_DEPLOY_HEALTH_TIMEOUT", "25")
    monkeypatch.setenv("APPAIFORGE_DEPLOY_HEALTH_INTERVAL", "1")
    from appaiforge.config import get_settings
    from appaiforge.drivers.docker_driver import DockerProvisioningDriver
    from test_deploy_versions import _probe

    get_settings.cache_clear()
    monkeypatch.setattr(DockerProvisioningDriver, "is_healthy", lambda self, slug: bool(_probe(_ctx["system"])))
    _ctx.clear()
    _ctx["tmp"], _ctx["monkeypatch"] = tmp_path, monkeypatch
    yield tmp_path
    if "system" in _ctx:
        _remove_containers(_ctx["system"].slug)
    server = _ctx.get("server")
    if server is not None:
        server.container.remove(force=True)


def _remove_containers(slug: str) -> None:
    import docker as docker_sdk

    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import dbgate_sidecar_name, httpsproxy_sidecar_name

    client = docker_sdk.from_env()
    for name in (httpsproxy_sidecar_name(slug), dbgate_sidecar_name(slug), system_container_name(slug)):
        try:
            client.containers.get(name).remove(force=True)
        except docker_sdk.errors.NotFound:
            pass


def _role(role: str) -> None:
    from appaiforge.config import get_settings

    _ctx["monkeypatch"].setenv("APPAIFORGE_INSTALLATION_ROLE", role)
    get_settings.cache_clear()


# ---- tipo e papel da instalação ----


@given("um portal de desenvolvimento")
def portal_dev(env, clean_db):
    _role("development")
    _ctx["owner"] = auth.create_user("dev@bdd.local", "pw", "editor")


@given("um portal de produção")
def portal_prod(env, clean_db):
    _role("production")
    _ctx["owner"] = auth.create_user("prod@bdd.local", "pw", "editor")


@when("um editor cria um sistema sem escolher o tipo")
def cria_sem_tipo():
    from appaiforge.services.systems import create_system

    _ctx["created"] = create_system(_ctx["owner"], "Sem tipo", "bdd-sem-tipo")


@then('o sistema é criado como "com agente"')
def criado_com_agente():
    assert _ctx["created"].kind == "agent"


@when("um editor tenta criar um sistema com agente")
def tenta_agente():
    from appaiforge.services.systems import AgentNotAllowedHere, create_system

    with pytest.raises(AgentNotAllowedHere) as exc:
        create_system(_ctx["owner"], "Agente", "bdd-agente", kind="agent")
    _ctx["error"] = str(exc.value)


@then("a criação é recusada explicando que este portal só aceita sistemas só implantação")
def recusada():
    assert "só implantação" in _ctx["error"] or "produção" in _ctx["error"]


# ---- sistema só implantação ligado ao repositório ----


@given("um sistema só implantação ativo ligado ao repositório")
def sistema_ligado(env, clean_db):
    from git_ssh_server import start_server

    from appaiforge import git_sync
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import provision_system
    from appaiforge.services import catalog, git_remote
    from appaiforge.services.systems import KIND_DEPLOY_ONLY, create_system, set_status

    catalog.ensure_presets()
    _ctx["server"] = server = start_server(str(env / "git-ssh"))
    server.init_repo()
    owner = _ctx["owner"] = auth.create_user("deploy@bdd.local", "pw", "editor")
    system = _ctx["system"] = create_system(owner, "Prod", f"bdd-dep-{os.urandom(3).hex()}", kind=KIND_DEPLOY_ONLY)
    provision_system(system)
    set_status(system.id, SystemStatus.active, "")
    view = git_remote.configure(system, owner, url=server.url)
    server.authorize(view["public_key"])
    git_remote.confirm_host_key(system, owner, git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)
    _ctx["refs_before"] = None


def _refs() -> str:
    return _ctx["server"].git("for-each-ref", "--format=%(refname) %(objectname)")


@then("nenhum processo de agente roda no container e nenhuma variável de LLM existe nele")
def sem_agente():
    from appaiforge.drivers import get_driver

    _, env_out, _ = get_driver().exec_in_app(_ctx["system"], ["env"])
    names = [line.split("=", 1)[0] for line in env_out.splitlines() if "=" in line]
    assert not [n for n in names if any(m in n for m in ("API_KEY", "AIDB_AGENT_PROFILE", "INFERENCE", "BROKER"))]
    _, procs, _ = get_driver().exec_in_app(
        _ctx["system"], ["sh", "-c", "for f in /proc/[0-9]*/cmdline; do tr '\\0' ' ' < $f; echo; done"])
    assert "opencode" not in procs and "claude" not in procs


@then(parsers.parse('a branch de destino é "{branch}" e o padrão de tags é "{pattern}"'))
def padroes(branch, pattern):
    from appaiforge.services import git_remote

    assert git_remote.get_view(_ctx["system"])["target_branch"] == branch
    assert deploy.get_deploy_settings(_ctx["system"].id).tag_pattern == pattern


@given(parsers.parse('o repositório tem as tags "{a}", "{b}", "{c}" e "{d}"'))
def tags(a, b, c, d):
    from test_deploy_versions import app_files

    sha = _ctx["server"].commit_as_human("main", app_files("X"), "base")
    for tag in (a, b, c, d):
        _ctx["server"].git("tag", tag, sha)


@then(parsers.parse('a lista de versões é "{a}", "{b}", "{c}"'))
def lista(a, b, c):
    assert [v["tag"] for v in deploy.list_versions(_ctx["system"])] == [a, b, c]


@given(parsers.parse('a versão "{tag}" na branch de destino com a app "{marker}"'))
def versao(tag, marker):
    from test_deploy_versions import app_files, release

    release(_ctx["server"], tag, app_files(marker))
    _ctx["refs_before"] = _refs()


@given(parsers.parse('a versão "{tag}" na branch de destino com uma app que não sobe'))
def versao_quebrada(tag):
    from test_deploy_versions import app_files, release

    release(_ctx["server"], tag, app_files("NUNCA", extra="raise SystemExit('quebrou')"))


@given(parsers.parse('a versão "{tag}" fora da branch de destino'))
def versao_fora(tag):
    from test_deploy_versions import app_files, release

    _ctx["server"].git("branch", "experimento", "main")
    release(_ctx["server"], tag, app_files("FORA"), branch="experimento")


@given(parsers.parse('a versão "{tag}" na branch de destino exigindo a conexão "{name}"'))
def versao_com_manifesto(tag, name):
    from test_deploy_versions import app_files, release

    manifest = json.dumps({"version": 1, "connections": [{"name": name, "kind": "postgres"}]})
    release(_ctx["server"], tag, {**app_files("COM-MANIFESTO"), ".aidb/manifest.json": manifest})


@given(parsers.parse('o editor implantou "{tag}"'))
def implantou(tag):
    assert deploy.deploy(_ctx["system"], tag, actor=_ctx["owner"])["status"] == "succeeded"


@when(parsers.parse('o editor implanta "{tag}"'))
def implanta(tag):
    _ctx["result"] = deploy.deploy(_ctx["system"], tag, actor=_ctx["owner"])


@given("o modo automático está ligado")
def automatico():
    from appaiforge.db import session_scope
    from appaiforge.models import DeploySettings

    with session_scope() as s:
        s.get(DeploySettings, _ctx["system"].id).mode = "automatic"


@when("a verificação automática roda")
def verificacao():
    _ctx["count_before"] = len(deploy.list_deployments(_ctx["system"].id))
    deploy.check_for_new(_ctx["system"], deploy.TRIGGER_POLLING)


@then(parsers.parse('a app responde "{marker}"'))
def app_responde(marker):
    from test_deploy_versions import _probe

    assert _probe(_ctx["system"]) == marker


@then(parsers.parse('o histórico mostra "{tag}" com origem "{trigger}" e resultado "{status}"'))
def historico(tag, trigger, status):
    last = deploy.list_deployments(_ctx["system"].id)[0]
    assert (last["tag"], last["trigger"], last["status"]) == (tag, trigger, status), last
    assert last["commit_sha"] and last["created_at"]


@then("nenhuma ref do repositório remoto mudou")
def refs_iguais():
    assert _refs() == _ctx["refs_before"]


@then("a implantação é recusada explicando que a versão não passou pela branch de destino")
def recusada_fora():
    assert _ctx["result"]["status"] == "failed"
    assert "não passou pela branch de destino" in _ctx["result"]["detail"]


@then(parsers.parse('a versão atual é "{tag}"'))
def atual(tag):
    assert deploy.current_deployment(_ctx["system"].id)["tag"] == tag


@then("nenhuma implantação foi feita")
def nenhuma():
    assert len(deploy.list_deployments(_ctx["system"].id)) == _ctx["count_before"] == 0


@when(parsers.parse('o webhook é chamado com o segredo "{secret}"'))
def webhook(secret):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from appaiforge.deploy_routes import router

    scheduled = []
    _ctx["monkeypatch"].setattr(deploy, "schedule_webhook_check", scheduled.append)
    _ctx["scheduled"] = scheduled
    app = FastAPI()
    app.include_router(router)
    deploy.webhook_secret(_ctx["system"].id)
    _ctx["response"] = TestClient(app).post(f"/hooks/gitlab/{_ctx['system'].id}", headers={"X-Gitlab-Token": secret})


@then("a chamada é recusada com 401")
def recusada_401():
    assert _ctx["response"].status_code == 401 and _ctx["scheduled"] == []


@then(parsers.parse('a implantação é recusada listando "{name}" como faltante'))
def faltante(name):
    assert _ctx["result"]["status"] == "failed" and name in _ctx["result"]["detail"]


@then("a implantação avisa que não pôde conferir as conexões")
def aviso_sem_manifesto():
    assert _ctx["result"]["status"] == "succeeded"
    assert "não tem manifesto" in _ctx["result"]["detail"]
