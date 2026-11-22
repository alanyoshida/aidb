"""Contrato: o agente opencode recebe o AGENTS.md do workspace (change fix-opencode-load-agents-md).

`opencode serve` da imagem base sobe como no container do sistema — cwd=/opencode-config com a
config gerada pelo portal, workspace em /workspace — contra um provedor falso que grava o corpo de
cada requisição ao modelo. Prova que:
- o conteúdo do AGENTS.md entra no prompt, e a versão nova vale já na mensagem seguinte;
- sem AGENTS.md (antes da primeira materialização) o agente responde normalmente;
- config de projeto no workspace (gravável pelo agente) continua ignorada.
"""

import json
import os
import time

import pytest

from appaiforge import __version__

pytestmark = [pytest.mark.integration]

BASE_IMAGE = os.environ.get("APPAIFORGE_TEST_BASE_IMAGE", f"appaiforge/base:{__version__}")

# Provedor openai-compatible mínimo: grava cada corpo (uma linha) e responde um stream válido.
FAKE_LLM = r'''
import http.server, json, sys
LOG = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        with open(LOG, "ab") as f:
            f.write(body.replace(b"\n", b" ") + b"\n")
        def chunk(delta, finish=None, usage=None):
            c = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "m",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage:
                c["usage"] = usage
            return b"data: " + json.dumps(c).encode() + b"\n\n"
        out = (chunk({"role": "assistant", "content": "ok"})
               + chunk({}, "stop", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
               + b"data: [DONE]\n\n")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9999), H).serve_forever()
'''


@pytest.fixture()
def agente(system, tmp_path):
    import docker

    from appaiforge.provisioning import write_opencode_config

    config_dir = tmp_path / "opencode-config"
    write_opencode_config(system, str(config_dir), [])
    config = json.loads((config_dir / "opencode.json").read_text())
    # só o provedor é trocado pelo falso; o resto (instructions, permissões) é o que o portal gera
    config["model"] = "fake/m"
    config["provider"] = {"fake": {
        "npm": "@ai-sdk/openai-compatible", "name": "fake",
        "options": {"baseURL": "http://127.0.0.1:9999/v1", "apiKey": "x"},
        "models": {"m": {}},
    }}
    (config_dir / "opencode.json").write_text(json.dumps(config))

    workspace = tmp_path / "workspace"
    (workspace / ".opencode").mkdir(parents=True)
    # config de projeto plantada no workspace: não pode ser carregada
    plantada = json.dumps({"instructions": ["/workspace/PLANTADA.md"]})
    (workspace / ".opencode" / "opencode.json").write_text(plantada)
    (workspace / "opencode.json").write_text(plantada)
    (workspace / "PLANTADA.md").write_text("MARCA-PLANTADA\n")

    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "fakellm.py").write_text(FAKE_LLM)

    container = docker.from_env().containers.run(
        BASE_IMAGE,
        entrypoint=["bash", "-c"],
        command=[
            "python3 /probe/fakellm.py /tmp/req.jsonl & "
            "cd /opencode-config && exec opencode serve --hostname 127.0.0.1 --port 4096"
        ],
        volumes={
            str(config_dir): {"bind": "/opencode-config", "mode": "ro"},
            str(workspace): {"bind": "/workspace", "mode": "rw"},
            str(probe): {"bind": "/probe", "mode": "ro"},
        },
        network_mode="none",
        detach=True,
        remove=True,
        labels={"appaiforge.role": "opencode-instructions-contract-test"},
    )

    def http(method: str, path: str, body: dict | None = None, timeout: int = 10) -> tuple[int, str]:
        cmd = ["curl", "-s", "-m", str(timeout), "-o", "/tmp/out", "-w", "%{http_code}", "-X", method,
               f"http://127.0.0.1:4096{path}"]
        if body is not None:
            cmd += ["-H", "content-type: application/json", "-d", json.dumps(body)]
        code = container.exec_run(cmd).output.decode().strip()
        return int(code or 0), container.exec_run(["cat", "/tmp/out"]).output.decode()

    try:
        for _ in range(60):
            if http("GET", "/command", timeout=2)[0] == 200:
                break
            time.sleep(1)
        _, body = http("POST", "/session", {"title": "contrato"})
        session = json.loads(body)["id"]

        def enviar(texto: str) -> str:
            """Manda uma mensagem (síncrona) e devolve os corpos enviados ao modelo por ela."""
            container.exec_run(["bash", "-c", ": > /tmp/req.jsonl"])
            code, _ = http("POST", f"/session/{session}/message",
                           {"parts": [{"type": "text", "text": texto}]}, timeout=60)
            assert code == 200
            return container.exec_run(["cat", "/tmp/req.jsonl"]).output.decode()

        yield {"enviar": enviar, "workspace": workspace}
    finally:
        container.remove(force=True)


def test_agents_md_do_workspace_entra_no_prompt_do_agente(agente):
    enviar, workspace = agente["enviar"], agente["workspace"]

    # antes da primeira materialização: sem AGENTS.md, o agente responde normalmente
    corpos = enviar("primeira")
    assert corpos.strip(), "o agente não chamou o modelo"
    assert "MARCA-GUIDELINES" not in corpos

    (workspace / "AGENTS.md").write_text("# Guidelines\nMARCA-GUIDELINES-1\n")
    corpos = enviar("segunda")
    assert "MARCA-GUIDELINES-1" in corpos

    # admin alterou as guidelines: a próxima mensagem já usa a versão nova
    (workspace / "AGENTS.md").write_text("# Guidelines\nMARCA-GUIDELINES-2\n")
    corpos = enviar("terceira")
    assert "MARCA-GUIDELINES-2" in corpos and "MARCA-GUIDELINES-1" not in corpos

    # config de projeto do workspace continua fora (confinamento)
    assert "MARCA-PLANTADA" not in corpos
