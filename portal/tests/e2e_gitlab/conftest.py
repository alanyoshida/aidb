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


def portal_python(code: str) -> str:
    """Prepara pré-condições pelos serviços do portal (o que o teste verifica continua no navegador)."""
    return _run(["docker", "exec", "-w", "/app/portal", PORTAL_CONTAINER, "python", "-c", code])


@pytest.fixture(scope="session", autouse=True)
def clean_stack():
    try:
        _run(["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-c", _local_reset_sql()])
    except (RuntimeError, FileNotFoundError):
        yield
        return
    restantes = set(_run(["docker", "exec", PG_CONTAINER, "psql", "-U", "appaiforge", "-t", "-A", "-c",
                          "SELECT slug FROM systems"]).split())
    for cid in _run(["docker", "ps", "-aq", "--filter", "label=appaiforge.managed=true",
                     "--filter", f"network={NETWORK}"]).split():
        name = _run(["docker", "inspect", "--format", "{{.Name}}", cid]).strip().lstrip("/")
        slug = name.removeprefix("appaiforge-sys-")
        if slug and slug not in restantes:
            for suffix in ("", "-dbgate", "-httpsproxy"):
                subprocess.run(["docker", "rm", "-f", f"appaiforge-sys-{slug}{suffix}"], capture_output=True, timeout=60)
    for directory in ("/gitdirs", "/git-relays"):
        for entry in _run(["docker", "exec", PORTAL_CONTAINER, "ls", "-1", directory]).split():
            if entry not in restantes and re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry):
                _run(["docker", "exec", PORTAL_CONTAINER, "rm", "-rf", f"{directory}/{entry}"])
    yield


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}
