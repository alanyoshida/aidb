"""Conftest E2E do modo OIDC (change add-oidc-sso, task 7.3).

Roda contra o stack dedicado `deploy/docker-compose.e2e-oidc.yml` (portal em
http://localhost:8082 com APPAIFORGE_AUTH_MODE=oidc + Keycloak em http://localhost:8180):

    docker compose -f deploy/docker-compose.e2e-oidc.yml up -d --build
    cd portal && uv run pytest tests/e2e_oidc

NÃO rode junto com a suíte `tests/e2e` (stack local, porta 8081): os contêineres de
sistema têm nome global. A limpeza de início é escopada: só sistemas de usuários
`@e2e-oidc.local`, contêineres na rede `appaiforge-e2e-oidc-net` e grupos `e2e-*`.
"""

import importlib.util
import os
import pathlib
import re
import subprocess

import pytest

BASE_URL = os.environ.get("APPAIFORGE_E2E_OIDC_BASE_URL", "http://localhost:8082").rstrip("/")
PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_OIDC_PG_CONTAINER", "appaiforge-e2e-oidc-postgres-1")
NETWORK = "appaiforge-e2e-oidc-net"
PORTAL_CONTAINER = os.environ.get("APPAIFORGE_E2E_OIDC_PORTAL_CONTAINER", "appaiforge-e2e-oidc-portal-1")


def _local_reset_sql() -> str:
    """Reaproveita o SQL de limpeza escopada da suíte local, trocando o domínio de teste."""
    path = pathlib.Path(__file__).parent.parent / "e2e" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_e2e_local_conftest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql = module._RESET_SQL.replace("@e2e.local", "@e2e-oidc.local")
    return sql + (
        "DELETE FROM system_groups WHERE group_id IN (SELECT id FROM groups WHERE name LIKE 'e2e-%');\n"
        "DELETE FROM groups WHERE name LIKE 'e2e-%';\n"
    )


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"comando falhou: {' '.join(cmd)}: {result.stderr.strip()}")
    return result.stdout


@pytest.fixture(scope="session", autouse=True)
def clean_stack():
    try:
        slugs_vivos = set(_run([
            "docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-t", "-A", "-c",
            "SELECT slug FROM systems",
        ]).split())
    except (RuntimeError, FileNotFoundError):
        yield
        return
    _run(["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-c", _local_reset_sql()])
    restantes = set(_run([
        "docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-t", "-A", "-c",
        "SELECT slug FROM systems",
    ]).split())
    for cid in _run([
        "docker", "ps", "-aq", "--filter", "label=appaiforge.managed=true", "--filter", f"network={NETWORK}",
    ]).split():
        name = _run(["docker", "inspect", "--format", "{{.Name}}", cid]).strip().lstrip("/")
        slug = name.removeprefix("appaiforge-sys-")
        if slug and slug not in restantes:
            # sidecars (network_mode container:) caem junto com o sistema pelo nome
            for suffix in ("", "-dbgate", "-httpsproxy"):
                subprocess.run(["docker", "rm", "-f", f"appaiforge-sys-{slug}{suffix}"],
                               capture_output=True, timeout=60)
    # repositórios git órfãos, fora do workspace (change isolate-workspace-repository): sem isto
    # um slug reaproveitado herdaria o histórico antigo
    try:
        for entry in _run(["docker", "exec", PORTAL_CONTAINER, "ls", "-1", "/gitdirs"]).split():
            if entry not in restantes and re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry):
                _run(["docker", "exec", PORTAL_CONTAINER, "rm", "-rf", f"/gitdirs/{entry}"])
    except RuntimeError:
        pass
    del slugs_vivos
    yield


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}
