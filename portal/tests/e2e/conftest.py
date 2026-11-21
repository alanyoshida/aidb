"""Conftest E2E: stack de teste dedicado via Traefik.

APPAIFORGE_E2E_BASE_URL aponta para o edge do stack (default http://localhost).
O stack de teste é DEDICADO (sempre fake, isolado do portal do usuário):
docker compose -f deploy/docker-compose.e2e.yml up -d --build

A limpeza de início de suíte é **escopada**: apaga somente usuários e sistemas
de teste (e-mails @e2e.local), preservando sistemas reais do ambiente de dev.
"""

import os
import re
import shutil
import subprocess

import pytest

BASE_URL = os.environ.get("APPAIFORGE_E2E_BASE_URL", "http://localhost:8081").rstrip("/")
PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_PG_CONTAINER", "appaiforge-e2e-postgres-1")
HOST_WORKSPACES = os.environ.get("APPAIFORGE_E2E_WORKSPACES_DIR", "/opt/appaiforge/workspaces-e2e")
PORTAL_CONTAINER = os.environ.get("APPAIFORGE_E2E_PORTAL_CONTAINER", "appaiforge-e2e-portal-1")

_RESET_SQL = """
CREATE TEMP TABLE _e2e_users AS SELECT id FROM users WHERE email LIKE '%@e2e.local';
CREATE TEMP TABLE _e2e_systems AS SELECT id FROM systems WHERE owner_id IN (SELECT id FROM _e2e_users);
DELETE FROM provider_keys WHERE provider NOT IN ('glm', 'anthropic', 'openai', 'openrouter');
DELETE FROM llm_provider WHERE is_preset = false;
DELETE FROM management_audit WHERE system_id IN (SELECT id FROM _e2e_systems)
  OR actor_id IN (SELECT id FROM _e2e_users);
DELETE FROM gate_decisions WHERE system_id IN (SELECT id FROM _e2e_systems)
  OR run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM gate_requests WHERE system_id IN (SELECT id FROM _e2e_systems)
  OR run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM run_events WHERE run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM agent_telemetry_spans WHERE run_id IN (SELECT id FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems));
DELETE FROM system_git_remotes WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM deployments WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM deploy_settings WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM checkpoints WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM token_usage WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM agent_runs WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM chat_sessions WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM db_connections WHERE system_id IN (SELECT id FROM _e2e_systems);
DELETE FROM allowed_domains WHERE system_id IN (SELECT id FROM _e2e_systems);
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


_SIDECAR_ROLES = ("dbgate-sidecar", "httpsproxy-sidecar")


def _e2e_sidecar_ids() -> list[str]:
    """Sidecars (gate de banco, change db-proxy-gate-data-plane; proxy
    HTTP(S) de saída, change agent-https-forward-proxy) sobem com
    `network_mode: container:<id do sistema>` (D1) — não têm entrada própria
    em `Networks`, então o filtro por rede do `docker ps` nunca os vê.
    Resolve pela cadeia (`HostConfig.NetworkMode`) até o container do
    sistema e só devolve o sidecar se ESSE estiver mesmo na rede do stack
    E2E — mesmo isolamento do filtro de rede acima, sem depender dele."""
    result = []
    try:
        candidates = []
        for role in _SIDECAR_ROLES:
            candidates += _run([
                "docker", "ps", "-aq", "--filter", f"label=appaiforge.role={role}",
            ]).split()
    except RuntimeError:
        return result
    for cid in candidates:
        try:
            mode = _run(["docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", cid]).strip()
            if not mode.startswith("container:"):
                continue
            target = mode.removeprefix("container:")
            networks = _run([
                "docker", "inspect", "--format",
                "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", target,
            ]).split()
        except RuntimeError:
            continue
        if "appaiforge-e2e-net" in networks:
            result.append(cid)
    return result


# Só nesta suíte: o stack local é dedicado aos testes, e vários deles criam sistemas como o admin
# de demonstração (ospec-*, editor-*, dbg-*...), que o _RESET_SQL (só @e2e.local) não apagava; os
# containers deles se acumulavam a cada execução. _RESET_SQL segue restrito, porque as suítes de
# OIDC e GitLab o reaproveitam, e o stack GitLab também serve ao piloto, com sistemas do admin.
_LOCAL_RESET_SQL = _RESET_SQL.replace(
    "WHERE owner_id IN (SELECT id FROM _e2e_users);",
    "WHERE owner_id IN (SELECT id FROM _e2e_users)\n"
    "  OR owner_id IN (SELECT id FROM users WHERE email = 'admin@appaiforge.local');",
    1,
)
assert _LOCAL_RESET_SQL != _RESET_SQL


def _cleanup() -> bool:
    """Limpa os dados de teste (@e2e.local e os sistemas do admin de demonstração, neste stack
    dedicado): linhas, containers e workspaces órfãos.
    Devolve False quando o stack não está disponível.

    Primeiro as linhas, depois os containers sem sistema: na ordem inversa, os containers dos
    sistemas de teste da execução anterior escapavam (o sistema ainda existia na hora da
    checagem) e ficavam rodando, com o opencode, até a execução seguinte da seguinte."""
    try:
        _run(["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-c", _LOCAL_RESET_SQL])
        slugs_vivos = set(_run([
            "docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-t", "-A", "-c",
            "SELECT slug FROM systems",
        ]).split())
    except (RuntimeError, FileNotFoundError):
        return False

    # containers de sistema cujo slug não existe mais no banco — SOMENTE na rede do
    # stack E2E, para nunca tocar containers do ambiente de dev/produção (isolamento)
    names = _run([
        "docker", "ps", "-aq",
        "--filter", "label=appaiforge.managed=true",
        "--filter", "network=appaiforge-e2e-net",
    ]).split()
    names += _e2e_sidecar_ids()
    for cid in names:
        try:
            name = _run(["docker", "inspect", "--format", "{{.Name}}", cid]).strip().lstrip("/")
            slug = name.removeprefix("appaiforge-sys-").removesuffix("-dbgate").removesuffix("-httpsproxy")
            if slug and slug not in slugs_vivos:
                _run(["docker", "rm", "-f", name])
        except RuntimeError:
            continue

    # workspaces órfãos (sem sistema correspondente) — nunca segue symlink para fora da raiz
    if os.path.isdir(HOST_WORKSPACES):
        for entry in os.listdir(HOST_WORKSPACES):
            path = os.path.join(HOST_WORKSPACES, entry)
            if entry not in slugs_vivos and os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)

    # repositórios git órfãos: vivem fora do workspace, num volume visível só ao portal (change
    # isolate-workspace-repository). Sem isto, um slug reaproveitado herdaria o histórico antigo.
    try:
        for entry in _run(["docker", "exec", PORTAL_CONTAINER, "ls", "-1", "/gitdirs"]).split():
            if entry not in slugs_vivos and re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry):
                _run(["docker", "exec", PORTAL_CONTAINER, "rm", "-rf", f"/gitdirs/{entry}"])
    except RuntimeError:
        pass
    return True


@pytest.fixture(scope="session", autouse=True)
def clean_stack():
    """Limpa antes (sobras de execuções interrompidas) e depois da sessão: os containers de
    sistema não fazem parte do compose e seguiriam rodando com a stack parada."""
    if not _cleanup():
        yield  # stack não disponível: nada a limpar
        return
    yield
    _cleanup()


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}
