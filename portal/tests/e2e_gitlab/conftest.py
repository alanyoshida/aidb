"""Conftest da suíte E2E com GitLab (change add-system-git-remote).

docker compose -f deploy/docker-compose.e2e-gitlab.yml up -d --build
python3 deploy/e2e-gitlab/init.py
cd portal && uv run pytest tests/e2e_gitlab
"""

import os
import re
import subprocess

import pytest

BASE_URL = os.environ.get("APPAIFORGE_E2E_GITLAB_BASE_URL", "http://localhost:8083").rstrip("/")
PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_GITLAB_PG_CONTAINER", "appaiforge-e2e-gitlab-postgres-1")
PORTAL_CONTAINER = os.environ.get("APPAIFORGE_E2E_GITLAB_PORTAL_CONTAINER", "appaiforge-e2e-gitlab-portal-1")
NETWORK = "appaiforge-e2e-gitlab-net"
# Portal de produção da mesma stack (change add-deploy-only-system): banco e volumes próprios.
PROD_BASE_URL = os.environ.get("APPAIFORGE_E2E_GITLAB_PROD_BASE_URL", "http://localhost:8084").rstrip("/")
PROD_PG_CONTAINER = os.environ.get("APPAIFORGE_E2E_GITLAB_PROD_PG_CONTAINER", "appaiforge-e2e-gitlab-postgres-prod-1")
PROD_PORTAL_CONTAINER = os.environ.get("APPAIFORGE_E2E_GITLAB_PROD_PORTAL_CONTAINER", "appaiforge-e2e-gitlab-portal-prod-1")


def _local_reset_sql() -> str:
    """O mesmo SQL de limpeza escopada da suíte E2E local (que já inclui o vínculo com o remoto)."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parent.parent / "e2e" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_e2e_local_conftest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._RESET_SQL


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"comando falhou: {' '.join(cmd)}: {result.stderr.strip()}")
    return result.stdout


def portal_python(code: str, container: str = PORTAL_CONTAINER) -> str:
    """Prepara pré-condições pelos serviços do portal (o que o teste verifica continua no navegador)."""
    return _run(["docker", "exec", "-w", "/app/portal", container, "python", "-c", code])


def _slugs(pg_container: str) -> set[str]:
    return set(_run(["docker", "exec", pg_container, "psql", "-U", "appaiforge", "-t", "-A", "-c",
                     "SELECT slug FROM systems"]).split())


def _cleanup() -> bool:
    """Limpa os dados de teste dos dois portais e o que ficou sem dono. Os containers de sistema
    dos dois estão na mesma rede: só sai o que não pertence a nenhum dos dois bancos. Devolve
    False quando nenhum dos dois stacks está disponível."""
    portals = [(PG_CONTAINER, PORTAL_CONTAINER), (PROD_PG_CONTAINER, PROD_PORTAL_CONTAINER)]
    live: dict[str, set[str]] = {}
    for pg, portal in portals:
        try:
            _run(["docker", "exec", pg, "psql", "-U", "appaiforge", "-c", _local_reset_sql()])
            live[portal] = _slugs(pg)
        except (RuntimeError, FileNotFoundError):
            continue
    if not live:
        return False
    restantes = set().union(*live.values())
    for cid in _run(["docker", "ps", "-aq", "--filter", "label=appaiforge.managed=true",
                     "--filter", f"network={NETWORK}"]).split():
        name = _run(["docker", "inspect", "--format", "{{.Name}}", cid]).strip().lstrip("/")
        slug = name.removeprefix("appaiforge-sys-")
        if slug and slug not in restantes:
            for suffix in ("", "-dbgate", "-httpsproxy"):
                subprocess.run(["docker", "rm", "-f", f"appaiforge-sys-{slug}{suffix}"], capture_output=True, timeout=60)
    for portal, slugs in live.items():
        for directory in ("/gitdirs", "/git-relays"):
            for entry in _run(["docker", "exec", portal, "ls", "-1", directory]).split():
                if entry not in slugs and re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry):
                    _run(["docker", "exec", portal, "rm", "-rf", f"{directory}/{entry}"])
    return True


@pytest.fixture(scope="session", autouse=True)
def clean_stack():
    """Limpa antes e depois da sessão: os containers de sistema não fazem parte do compose e
    seguiriam rodando (com o agente) depois dos testes."""
    if not _cleanup():
        yield
        return
    yield
    _cleanup()


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}
