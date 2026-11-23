"""Teste de saúde da app no driver Kubernetes (readinessProbe e checagem da implantação). Roda o
comando de verdade num shell, contra um servidor HTTP local. Achado no piloto: com a porta
fechada o teste antigo passava ("000" + "000"), e a implantação aprovou uma app morta."""

import http.server
import os
import shutil
import socket
import subprocess
import threading

import pytest

from appaiforge.drivers.kubernetes_driver import _agent_container, _health_check_command

# Na CI (`CI` definido), a falta do curl é falha, não pulo (change add-ci-workflow, D4).
pytestmark = pytest.mark.skipif(shutil.which("curl") is None and not os.environ.get("CI"), reason="curl não instalado")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _passes(port: int) -> bool:
    return subprocess.run(_health_check_command(port), capture_output=True, timeout=20).returncode == 0


def _serve(status: int) -> tuple[http.server.HTTPServer, int]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_porta_fechada_falha():
    assert not _passes(_free_port())


@pytest.mark.parametrize("status, ok", [(200, True), (403, True), (404, True), (500, False), (502, False)])
def test_resposta_abaixo_de_500_conta_como_no_ar(status, ok):
    server, port = _serve(status)
    try:
        assert _passes(port) is ok
    finally:
        server.shutdown()


def test_container_do_agente_sem_liveness_probe():
    """Com a app quebrada, uma livenessProbe reiniciaria o container inteiro (agente incluído)."""
    from types import SimpleNamespace

    system = SimpleNamespace(slug="s", id="i", execution_mode="legacy", agent_profile="opencode")
    profile = {"image": "img", "config_mount_path": "/cfg", "harness_port": 4096}
    container = _agent_container(system, profile, {}, SimpleNamespace(app_port=8080, container_cpus=1,
                                                                    container_mem_mb=512, container_disk_gb=1))
    assert container.readiness_probe is not None
    assert container.liveness_probe is None


def test_secrets_de_pull_dos_pods_de_sistema():
    from types import SimpleNamespace

    from appaiforge.drivers.kubernetes_driver import _image_pull_secrets

    assert _image_pull_secrets(SimpleNamespace(k8s_image_pull_secrets="")) is None
    refs = _image_pull_secrets(SimpleNamespace(k8s_image_pull_secrets=" registro-a, registro-b ,"))
    assert [r.name for r in refs] == ["registro-a", "registro-b"]


def _pod(images: dict, secrets: list[str]):
    from types import SimpleNamespace

    return SimpleNamespace(spec=SimpleNamespace(
        containers=[SimpleNamespace(name=n, image=i) for n, i in images.items()],
        image_pull_secrets=[SimpleNamespace(name=s) for s in secrets] or None,
    ))


def test_divergencia_de_spec_recria_o_pod(monkeypatch):
    """Imagens e Secrets de pull vêm da configuração, mas o spec do Pod é imutável: a
    reconciliação recria o Pod que ainda usa a configuração anterior."""
    from types import SimpleNamespace

    from appaiforge.drivers import kubernetes_driver
    from appaiforge.services import systems

    monkeypatch.setattr(systems, "get_system", lambda sid: SimpleNamespace(agent_profile="opencode"))
    settings = SimpleNamespace(base_image="r/base:2", claude_code_image="r/cc:2", k8s_image_pull_secrets="reg")
    monkeypatch.setattr("appaiforge.config.get_settings", lambda: settings)
    current = {"agent": "r/base:2", "git": "r/base:2", "httpsproxy": "r/base:2"}

    assert kubernetes_driver._spec_drift(_pod(current, ["reg"]), "s", settings) == ""
    assert "imagePullSecrets" in kubernetes_driver._spec_drift(_pod(current, []), "s", settings)
    old_git = {**current, "git": "appaiforge/base:0.1.0"}
    assert "git" in kubernetes_driver._spec_drift(_pod(old_git, ["reg"]), "s", settings)
    old_agent = {**current, "agent": "appaiforge/base:0.1.0"}
    assert "agent" in kubernetes_driver._spec_drift(_pod(old_agent, ["reg"]), "s", settings)
