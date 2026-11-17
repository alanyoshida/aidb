"""OpenSpec no container do sistema (change add-openspec-to-system-container, tasks 2.2 e 4.2).

- bootstrap pelo supervisor num container de sistema real (driver Docker): sistema novo sobe com
  `openspec/` e os comandos `/opsx-*`; uma change criada à mão sobrevive à recriação do container;
- contrato com o opencode pinado na imagem base: `GET /command` lista os comandos com descrição e
  `POST /session/{id}/command` expande o template (o que o adapter do portal assume).
"""

import json
import os
import time

import pytest


pytestmark = [pytest.mark.integration]

BASE_IMAGE = os.environ.get("APPAIFORGE_TEST_BASE_IMAGE", "appaiforge/base:0.1.0")


def _client():
    import docker

    return docker.from_env()


def _wait_file(path: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path):
            return True
        time.sleep(0.5)
    return False


def test_sistema_novo_sobe_com_openspec_e_change_sobrevive_a_recriacao(system):
    from appaiforge.config import get_settings
    from appaiforge.provisioning import provision_system, stop_and_remove

    provision_system(system)
    workspace = os.path.join(get_settings().workspaces_dir, system.slug)
    assert _wait_file(os.path.join(workspace, ".opencode", "commands", "opsx-propose.md")), os.listdir(workspace)
    for cmd in ("opsx-explore", "opsx-apply", "opsx-archive"):
        assert os.path.isfile(os.path.join(workspace, ".opencode", "commands", f"{cmd}.md"))
    config = open(os.path.join(workspace, "openspec", "config.yaml")).read()
    assert "pt-BR" in config

    change = os.path.join(workspace, "openspec", "changes", "filtro-por-data")
    os.makedirs(change, exist_ok=True)
    with open(os.path.join(change, "proposal.md"), "w") as f:
        f.write("# Proposta\n\nfiltro por data\n")
    with open(os.path.join(workspace, "openspec", "config.yaml"), "a") as f:
        f.write("# ajuste do editor\n")
    marker = os.path.join(workspace, ".opencode", "commands", "opsx-propose.md")
    os.remove(marker)  # o update repõe os comandos

    stop_and_remove(system)
    provision_system(system)
    assert _wait_file(marker)
    assert open(os.path.join(change, "proposal.md")).read() == "# Proposta\n\nfiltro por data\n"
    assert "# ajuste do editor" in open(os.path.join(workspace, "openspec", "config.yaml")).read()


@pytest.fixture()
def opencode_serve():
    """`opencode serve` da imagem base, num workspace inicializado pelo OpenSpec da própria imagem."""
    client = _client()
    container = client.containers.run(
        BASE_IMAGE,
        entrypoint=["bash", "-c"],
        command=[
            "mkdir -p /tmp/ws && openspec init --tools opencode --language pt-BR /tmp/ws >/dev/null 2>&1; "
            "cd /tmp/ws && exec opencode serve --hostname 127.0.0.1 --port 4096"
        ],
        detach=True,
        remove=True,
        labels={"appaiforge.role": "openspec-contract-test"},
    )

    def http(method: str, path: str, body: dict | None = None, timeout: int = 10) -> tuple[int, str]:
        cmd = ["curl", "-s", "-m", str(timeout), "-o", "/tmp/out", "-w", "%{http_code}", "-X", method,
               f"http://127.0.0.1:4096{path}"]
        if body is not None:
            cmd += ["-H", "content-type: application/json", "-d", json.dumps(body)]
        code = container.exec_run(cmd).output.decode().strip()
        out = container.exec_run(["cat", "/tmp/out"]).output.decode()
        return int(code or 0), out

    try:
        for _ in range(60):
            code, _ = http("GET", "/command", timeout=2)
            if code == 200:
                break
            time.sleep(1)
        yield http
    finally:
        container.remove(force=True)


def test_contrato_opencode_lista_e_expande_comandos(opencode_serve):
    code, body = opencode_serve("GET", "/command")
    assert code == 200
    commands = {c["name"]: c for c in json.loads(body)}
    propose = commands["opsx-propose"]
    assert propose["source"] == "command" and propose["description"]
    assert "$ARGUMENTS" in propose["template"]
    assert {c["source"] for c in commands.values()} <= {"command", "skill"}

    code, body = opencode_serve("POST", "/session", {"title": "contrato"})
    session = json.loads(body)["id"]
    # o endpoint de comando só responde ao fim da execução (sem chave de LLM aqui): dispara e
    # confere a mensagem de usuário gravada, que precisa ser o template expandido
    opencode_serve("POST", f"/session/{session}/command",
                   {"command": "opsx-explore", "arguments": "filtro por data"}, timeout=3)
    code, body = opencode_serve("GET", f"/session/{session}/message")
    texts = [p.get("text", "") for m in json.loads(body) if m["info"]["role"] == "user"
             for p in m["parts"] if p.get("type") == "text"]
    explore_prefix = commands["opsx-explore"]["template"].split("$ARGUMENTS", 1)[0].strip()[:200]
    assert texts and texts[0].startswith(explore_prefix)
