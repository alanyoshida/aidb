"""Conftest E2E: stack de teste dedicado via Traefik.

APPAIFORGE_E2E_BASE_URL aponta para o edge do stack (default http://localhost).
O stack de teste é DEDICADO (sempre fake, isolado do portal do usuário):
docker compose -f deploy/docker-compose.e2e.yml up -d --build

A limpeza de início de suíte é **escopada**: apaga somente usuários e sistemas
de teste (e-mails @e2e.local), preservando sistemas reais do ambiente de dev.
"""

import os
import shutil
import subprocess

import pytest

BASE_URL = os.environ.get("APPAIFORGE_E2E_BASE_URL", "http://localhost:8081").rstrip("/")
PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_PG_CONTAINER", "appaiforge-e2e-postgres-1")
HOST_WORKSPACES = os.environ.get("APPAIFORGE_E2E_WORKSPACES_DIR", "/opt/appaiforge/workspaces-e2e")

_RESET_SQL = """
CREATE TEMP TABLE _e2e_users AS SELECT id FROM users WHERE email LIKE '%@e2e.local';
CREATE TEMP TABLE _e2e_systems AS SELECT id FROM systems WHERE owner_id IN (SELECT id FROM _e2e_users);
DELETE FROM gate_decisions WHERE system_id IN (SELECT id FROM _e2e_systems)
  OR run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM run_events WHERE run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM checkpoints WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM token_usage WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM chat_sessions WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM db_connections WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM system_groups WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM group_members WHERE user_id IN (SELECT id FROM _e2e_users);
DELETE FROM sessions WHERE user_id IN (SELECT id FROM _e2e_users);
DELETE FROM systems WHERE id IN (SELECT id FROM _e2e_systems);
DELETE FROM groups WHERE NOT EXISTS (SELECT 1 FROM group_members gm WHERE gm.group_id = groups.id)
  AND (name LIKE 'equipe-%' OR name LIKE 'jornada-%');
DELETE FROM users WHERE id IN (SELECT id FROM _e2e_users);
"""


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"comando falhou: {' '.join(cmd)}: {result.stderr.strip()}")
    return result.stdout


@pytest.fixture(scope="session", autouse=True)
def clean_stack():
    """Limpa somente dados de teste (@e2e.local): containers, linhas e workspaces órfãos."""
    try:
        slugs_vivos = set(_run([
            "docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-t", "-A", "-c",
            "SELECT slug FROM systems",
        ]).split())
    except (RuntimeError, FileNotFoundError):
        yield  # stack não disponível: nada a limpar
        return

    # containers de sistema cujo slug não existe mais no banco
    names = _run(["docker", "ps", "-aq", "--filter", "label=appaiforge.managed=true"]).split()
    for cid in names:
        try:
            name = _run(["docker", "inspect", "--format", "{{.Name}}", cid]).strip().lstrip("/")
            slug = name.removeprefix("appaiforge-sys-")
            if slug and slug not in slugs_vivos:
                _run(["docker", "rm", "-f", name])
        except RuntimeError:
            continue

    _run(["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-c", _RESET_SQL])

    # workspaces órfãos (sem sistema correspondente) — nunca segue symlink para fora da raiz
    if os.path.isdir(HOST_WORKSPACES):
        for entry in os.listdir(HOST_WORKSPACES):
            path = os.path.join(HOST_WORKSPACES, entry)
            if entry not in slugs_vivos and os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)

    yield


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}
