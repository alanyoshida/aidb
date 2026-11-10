"""Ponta a ponta do perfil claude-code (change add-claude-code-agent-profile,
task 7.3) — critério de sucesso negativo da etapa 7 do roadmap.

Docker real, shim real, CLI `claude` real dentro do container real,
`ClaudeCodeHarness` real, `AgentQueue`/checkpoint real (o mesmo caminho de
produção que um sistema `opencode` usa). A única parte fabricada é o
backend do modelo (`fixtures/fake_anthropic.js`, mesmo racional do spike de
tasks.md 1.1-1.4): sem chave da Anthropic disponível no momento, então o
`ANTHROPIC_BASE_URL` do sistema aponta pra esse stub em vez do broker real.

Rodar este teste de ponta a ponta de verdade achou um bug pré-existente,
fora do escopo original desta change, em `base-image/httpproxy/proxy.py` —
o relay HTTP absoluto (destino `http://`, usado pelo `ANTHROPIC_BASE_URL`
deste teste e do broker real em produção) descartava o corpo e os headers
da requisição inteiros, exceto `Host`. Sem o corpo chegando no destino, o
stub nunca via o `tool_result` do turno anterior e o `claude -p` entrava
num loop fazendo a mesma chamada de ferramenta pra sempre (ver design.md,
"Achado crítico da verificação real"). Corrigido em separado (repasse de
headers e corpo da requisição, inclusive `Transfer-Encoding: chunked`) —
ver `base-image/httpproxy/test_proxy.py` pelos testes de regressão do
proxy em si. Este teste deixou de precisar do `skip`."""

import os
import time

import pytest

pytestmark = [pytest.mark.integration]

STUB_PORT = 18080
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _client():
    import docker

    return docker.from_env()


@pytest.fixture()
def fake_anthropic_stub():
    """Container do stub (fixtures/fake_anthropic.js) na mesma rede docker
    que o sistema usa — alcançável pelo nome do container (DNS do Docker
    entre containers, diferente de alcançar o container do sistema a partir
    do processo de teste no host, que precisa do IP direto - ver harness_ip)."""
    from appaiforge.config import get_settings
    from appaiforge.provisioning import ensure_network

    ensure_network()
    client = _client()
    name = f"claude-code-e2e-stub-{os.urandom(4).hex()}"
    container = client.containers.run(
        "node:22-slim",
        command=["node", "/fixtures/fake_anthropic.js", str(STUB_PORT)],
        name=name,
        network=get_settings().docker_network,
        volumes={FIXTURES_DIR: {"bind": "/fixtures", "mode": "ro"}},
        environment={"SPIKE_BASH_COMMAND": "echo e2e-ok > e2e_marker.txt"},
        detach=True,
        remove=False,
    )
    try:
        yield name
    finally:
        container.remove(force=True)


@pytest.fixture()
def claude_code_e2e_system(docker_env, clean_db, fake_anthropic_stub, monkeypatch):
    from appaiforge import auth
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system
    from tests.integration.conftest import remove_system_containers

    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_ENABLED", "true")
    monkeypatch.setenv("APPAIFORGE_INFERENCE_BROKER_URL", f"http://{fake_anthropic_stub}:{STUB_PORT}")
    get_settings.cache_clear()

    catalog.ensure_presets()
    editor = auth.create_user("e2e-cc@t.local", "pw", UserType.editor.value)
    sys = create_system(
        editor, "Sistema E2E Claude Code", f"e2e-cc-{os.urandom(3).hex()}",
        agent_profile="claude-code", provider="anthropic",
    )
    yield sys, editor
    remove_system_containers(sys.slug)
    get_settings.cache_clear()


def _container_ip(container, network: str) -> str:
    container.reload()
    return container.attrs["NetworkSettings"]["Networks"][network]["IPAddress"]


def _wait_shim_ready(base_url: str, timeout: float = 30.0) -> None:
    import httpx

    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            httpx.post(f"{base_url}/session", timeout=2.0).raise_for_status()
            return
        except Exception as exc:  # noqa: BLE001 — só pra decidir tentar de novo
            last_exc = exc
            time.sleep(0.5)
    raise TimeoutError(f"shim claude-code não respondeu em {timeout}s: {last_exc}")


def _wait_run(queue, run_id: str, timeout: float = 60.0):
    from appaiforge.db import session_scope
    from appaiforge.models import AgentRun, RunStatus

    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run and run.status not in (RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval):
                return run.status, run.summary
        time.sleep(0.3)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


def test_sistema_claude_code_ponta_a_ponta_com_checkpoint(claude_code_e2e_system, fake_anthropic_stub, monkeypatch):
    import appaiforge.agent_queue as agent_queue_module
    from appaiforge.agent_profiles import get_profile
    from appaiforge.agent_queue import AgentQueue
    from appaiforge.checkpoints import list_checkpoints, workspace_dir
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.harness.opencode import OpencodeHarness
    from appaiforge.models import RunStatus
    from appaiforge.provisioning import provision_system

    system, editor = claude_code_e2e_system
    provision_system(system)

    client = _client()
    container = client.containers.get(system_container_name(system.slug))
    ip = _container_ip(container, get_settings().docker_network)
    profile = get_profile(system.agent_profile)
    base_url = f"http://{ip}:{profile['harness_port']}"
    _wait_shim_ready(base_url)

    # `harness_for` só usa o harness injetado no construtor para o
    # protocolo PADRÃO da plataforma (opencode-http); para claude-code-headless
    # ele sempre resolve via HARNESS_IMPLEMENTATIONS[...] -> ClaudeCodeHarness(_harness_url),
    # que resolve o endereço por nome de container (só alcançável de dentro
    # da rede docker, onde o portal real roda). O teste roda no host, fora
    # dessa rede — então troca `_harness_url` por resolução direta por IP,
    # exatamente o mesmo papel que o nome de container cumpre em produção.
    monkeypatch.setattr(agent_queue_module, "_harness_url", lambda _sys: base_url)
    queue = AgentQueue(OpencodeHarness(agent_queue_module._harness_url))

    run = queue.enqueue(system.id, editor.id, "registre que terminamos o teste", chat_session_id=None)
    status, summary = _wait_run(queue, run.id)

    assert status == RunStatus.succeeded, f"run falhou: {summary}"

    checkpoints = list_checkpoints(system)
    assert len(checkpoints) == 1
    assert checkpoints[0]["git_sha"]

    marker_path = os.path.join(workspace_dir(system), "e2e_marker.txt")
    assert os.path.isfile(marker_path)
    assert open(marker_path).read().strip() == "e2e-ok"
