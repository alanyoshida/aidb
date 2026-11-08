"""Integração com Docker real do proxy HTTP(S) de saída (change
`agent-https-forward-proxy`). 443/80 saíram da lista estática de portas
liberadas do agente (etapa 5 estendida) — este teste prova que a única
saída HTTP(S) possível é pelo sidecar, que só libera a allow-list
calculada para o sistema (provedor de LLM/broker + registros de pacote, ou
a lista do modo restrito).

Requer a imagem base (appaiforge/base:0.1.0) com o proxy HTTP(S) embarcado
e acesso real à internet (pypi.org, o host do provedor) de dentro do
container — mesmo requisito já aceito por `test_network_perimeter.py`.
"""

import json
import time

import pytest

pytestmark = pytest.mark.integration


def _client():
    import docker

    return docker.from_env()


def _wait_container_running(name: str) -> None:
    import docker as docker_sdk

    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if _client().containers.get(name).status == "running":
                return
        except docker_sdk.errors.NotFound:
            pass
        time.sleep(1)
    raise AssertionError(f"container {name} não subiu em 60s")


def _wait_proxy_ready(container, deadline_s: float = 20) -> None:
    """O sidecar relata o container criado antes do processo asyncio dentro
    dele estar de fato escutando — espera um destino sempre-permitido
    (registro de pacote) responder antes de testar o resto."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if _curl_via_proxy(container, "pypi.org") == 200:
            return
        time.sleep(0.5)
    raise AssertionError("proxy HTTP(S) do sistema não respondeu a tempo")


def _curl_via_proxy(container, host: str, timeout: int = 10) -> int:
    """Código HTTP (ou -1 se a conexão falhar) de um GET via `CONNECT` no
    proxy do próprio sistema, de dentro do container."""
    from appaiforge.provisioning import HTTPS_PROXY_PORT

    result = container.exec_run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout),
         "-x", f"http://127.0.0.1:{HTTPS_PROXY_PORT}", f"https://{host}"]
    )
    out = result.output.decode().strip()
    try:
        return int(out)
    except ValueError:
        return -1


def test_destino_permitido_funciona_e_direto_na_443_e_negado(system, docker_env):
    """Caso de aceitação principal: o host do provedor configurado alcança
    de verdade pelo proxy; a mesma porta 443, direto (contornando o proxy),
    fica negada pelo Landlock (D5) — o único jeito de sair em 443 passou a
    ser o proxy."""
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode
    from appaiforge.provisioning import provision_system

    assert system.execution_mode == ExecutionMode.sandboxed, (
        "este host suporta Landlock (confirmado em outros testes); se este assert falhar, "
        "o teste não prova nada sobre confinamento de rede"
    )

    provision_system(system)
    container = _client().containers.get(system_container_name(system.slug))
    _wait_proxy_ready(container)

    code = _curl_via_proxy(container, "pypi.org")
    assert code == 200, f"pypi.org deveria estar sempre na allow-list padrão (registro de pacote), código {code}"

    script = """
import sys, socket, json
sys.path.insert(0, "/opt/afsupervisor")
from afsupervisor import sandbox
import os

profile = json.load(open("/opencode-config/agent-profile.json"))
sandbox.apply_landlock_net(
    connect_tcp_ports=profile["connect_tcp_ports"],
    bind_tcp_ports=profile["bind_tcp_ports"],
)
try:
    socket.create_connection(("pypi.org", 443), timeout=5).close()
    print(json.dumps({"direto_443": "PASSOU (inesperado)"}))
except PermissionError as exc:
    print(json.dumps({"direto_443": f"negado: {exc}"}))
"""
    result = container.exec_run(["python3", "-c", script])
    assert result.exit_code == 0, result.output.decode()
    resultado = json.loads(result.output.decode().strip().splitlines()[-1])
    assert resultado["direto_443"].startswith("negado:"), resultado


def test_destino_fora_da_allowlist_e_recusado_sem_tocar_a_rede(system, docker_env):
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)
    container = _client().containers.get(system_container_name(system.slug))
    _wait_proxy_ready(container)

    code = _curl_via_proxy(container, "example.com")
    assert code != 200
    # 000 (curl não recebeu corpo nenhum do destino real) ou o -1 do parse: o
    # proxy recusa com 403 antes de abrir qualquer conexão com example.com
    assert code in (-1, 0)


def test_pacotes_pip_e_npm_funcionam_atras_do_proxy(system, docker_env):
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system

    provision_system(system)
    container = _client().containers.get(system_container_name(system.slug))
    _wait_proxy_ready(container)

    pip_result = container.exec_run(
        ["pip", "install", "--target", "/tmp/pipdest", "--no-cache-dir", "six"]
    )
    assert pip_result.exit_code == 0, pip_result.output.decode()

    npm_result = container.exec_run(
        ["npm", "install", "--prefix", "/tmp/npmdest", "left-pad"]
    )
    assert npm_result.exit_code == 0, npm_result.output.decode()


def test_internet_desabilitada_recusa_tudo_e_modo_restrito_so_libera_a_lista(system, docker_env):
    from appaiforge.edge import system_container_name
    from appaiforge.provisioning import provision_system
    from appaiforge.services import network_policy

    provision_system(system)
    container = _client().containers.get(system_container_name(system.slug))
    _wait_proxy_ready(container)
    assert _curl_via_proxy(container, "pypi.org") == 200

    network_policy.set_internet_enabled(system.id, False)
    # a atualização do sidecar é assíncrona (thread, mesmo padrão do refresh
    # de conexões) — espera o container do sidecar devolver code != 200
    deadline = time.time() + 15
    code = _curl_via_proxy(container, "pypi.org")
    while code == 200 and time.time() < deadline:
        time.sleep(0.5)
        code = _curl_via_proxy(container, "pypi.org")
    assert code != 200, "internet desabilitada deveria recusar até os registros de pacote"

    network_policy.set_internet_enabled(system.id, True)
    network_policy.set_restricted_network(system.id, True)
    network_policy.add_allowed_domain(system.id, "example.org")

    deadline = time.time() + 15
    code = _curl_via_proxy(container, "example.org")
    while code != 200 and time.time() < deadline:
        time.sleep(0.5)
        code = _curl_via_proxy(container, "example.org")
    assert code == 200, "domínio cadastrado no modo restrito deveria ser liberado"

    # o host do provedor (que estaria na allow-list padrão) não entra no modo
    # restrito a menos que alguém cadastre explicitamente — only a lista conta
    assert _curl_via_proxy(container, "api.z.ai") != 200
