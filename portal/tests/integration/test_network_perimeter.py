"""Integração com Docker real do confinamento de rede do agente (etapa 5 do
roadmap de confinamento, change agent-network-perimeter).

Landlock por filesystem (etapa 2) não cobre rede: o agente confinado em
`sandboxed` sempre pôde conectar direto no Postgres/MySQL real, por fora do
proxy de gate de banco (etapa 4), bastando descobrir o endereço. Este teste
prova que isso fecha: um script real, aplicando o mesmo `apply_landlock_net`
de produção com o perfil real escrito pelo provisionamento, consegue
conectar no `agent_port` do proxy mas não na porta real do Postgres —
mesmo quando as duas são alcançáveis na rede (o teste usa o gateway Docker
como host das duas, não "localhost", que só faz sentido do lado de fora do
container; ver test_db_gate_proxy.py para o mesmo achado).

Requer a imagem base (appaiforge/base:0.1.0) com o Landlock de rede embarcado.
"""

import json
import time

import pytest

pytestmark = pytest.mark.integration


def _client():
    import docker

    return docker.from_env()


def _gateway_ip(network_name: str) -> str:
    net = _client().networks.get(network_name)
    return net.attrs["IPAM"]["Config"][0]["Gateway"]


def _wait_sidecar_running(slug: str) -> None:
    from appaiforge.provisioning import dbgate_sidecar_name

    import docker as docker_sdk

    deadline = time.time() + 60
    name = dbgate_sidecar_name(slug)
    while time.time() < deadline:
        try:
            sidecar = _client().containers.get(name)
            if sidecar.status == "running":
                return
        except docker_sdk.errors.NotFound:
            pass
        time.sleep(1)
    raise AssertionError(f"sidecar {name} não subiu em 60s")


def _wait_dbgate_port_ready(container, port: int, deadline_s: float = 20) -> None:
    """O sidecar (container Docker) fica `running` antes do processo asyncio
    dentro dele terminar de montar os listeners — mesmo achado do proxy
    HTTP(S) de saída (ver `_wait_proxy_ready` em test_https_proxy.py):
    `_wait_sidecar_running` só prova que o container existe, não que a porta
    já aceita conexão. Sem este passo o teste corre direto pro script com
    Landlock e vê `ConnectionRefusedError` nesse intervalo, por fora de
    qualquer coisa que o Landlock decida."""
    deadline = time.time() + deadline_s
    script = (
        "import socket\n"
        f"s = socket.create_connection(('127.0.0.1', {port}), timeout=1)\n"
        "s.close()\n"
    )
    while time.time() < deadline:
        if container.exec_run(["python3", "-c", script]).exit_code == 0:
            return
        time.sleep(0.5)
    raise AssertionError(f"proxy de gate de banco não respondeu em {port} a tempo")


def test_agente_sandboxed_alcanca_o_proxy_mas_nao_o_postgres_real(system, docker_env, live_pg):
    from appaiforge.config import get_settings
    from appaiforge.edge import system_container_name
    from appaiforge.models import ExecutionMode
    from appaiforge.provisioning import db_connections_manifest, ensure_network, provision_system
    from appaiforge.services import connections

    assert system.execution_mode == ExecutionMode.sandboxed, (
        "este host suporta Landlock (confirmado em outros testes); se este assert falhar, "
        "o sistema não nasceu sandboxed e o teste não prova nada sobre confinamento de rede"
    )

    ensure_network()
    gateway = _gateway_ip(get_settings().docker_network)

    provision_system(system)
    connections.register_connection(
        system, "vendas", gateway, live_pg["port"], live_pg["database"], live_pg["username"], live_pg["password"],
    )
    _wait_sidecar_running(system.slug)

    manifest = db_connections_manifest(system.id)
    (entry,) = [m for m in manifest if m["name"] == "vendas"]
    agent_port = entry["agent_port"]

    container = _client().containers.get(system_container_name(system.slug))
    profile_json = container.exec_run(["cat", "/opencode-config/agent-profile.json"]).output.decode()
    profile = json.loads(profile_json)
    assert agent_port in profile["connect_tcp_ports"], "agent_port da conexão real deveria estar na lista"
    assert live_pg["port"] not in profile["connect_tcp_ports"], (
        "a porta real do Postgres não deveria estar liberada — só a do proxy"
    )
    _wait_dbgate_port_ready(container, agent_port)

    script = f"""
import sys, socket, json
sys.path.insert(0, "/opt/afsupervisor")
from afsupervisor import sandbox

sandbox.apply_landlock_net(
    connect_tcp_ports={profile["connect_tcp_ports"]!r},
    bind_tcp_ports={profile["bind_tcp_ports"]!r},
)

resultado = {{}}
try:
    s = socket.create_connection(("127.0.0.1", {agent_port}), timeout=5)
    resultado["proxy"] = "ok"
    s.close()
except Exception as exc:
    resultado["proxy"] = f"{{type(exc).__name__}}: {{exc}}"

try:
    s = socket.create_connection(("{gateway}", {live_pg["port"]}), timeout=5)
    resultado["bypass_postgres_real"] = "PASSOU (inesperado)"
    s.close()
except PermissionError as exc:
    resultado["bypass_postgres_real"] = f"negado: {{exc}}"
except Exception as exc:
    resultado["bypass_postgres_real"] = f"{{type(exc).__name__}}: {{exc}}"

print(json.dumps(resultado))
"""
    result = container.exec_run(["python3", "-c", script])
    assert result.exit_code == 0, result.output.decode()
    resultado = json.loads(result.output.decode().strip().splitlines()[-1])

    assert resultado["proxy"] == "ok", resultado
    assert resultado["bypass_postgres_real"].startswith("negado:"), resultado
