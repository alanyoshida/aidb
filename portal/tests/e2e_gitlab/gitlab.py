"""Helpers da API do GitLab da stack E2E (change add-system-git-remote). O teste faz o papel do
humano: cria o projeto, cadastra a chave, faz merge e confere o resultado."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("AIDB_E2E_GITLAB_API", "http://localhost:8929/api/v4")
ROOT_TOKEN = "aidb-e2e-root-somente-local-0001"
GROUP = "aidb"
# Como o portal (dentro da rede da stack) alcança o GitLab.
INTERNAL_SSH = "ssh://git@gitlab:22"
INTERNAL_API = "http://gitlab"


def api(method: str, path: str, data: dict | None = None, *, token: str = ROOT_TOKEN, ok404: bool = False):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"PRIVATE-TOKEN": token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if ok404 and exc.code == 404:
            return None
        raise AssertionError(f"{method} {path}: {exc.code} {exc.read().decode(errors='replace')[:300]}") from None


def q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def create_system_project(name: str) -> dict:
    """Projeto vazio no grupo, como um time criaria para um sistema: CI no projeto de modelos,
    merge sem squash e só com pipeline verde, `main` (ninguém faz push) e `homolog`
    (mantenedores fazem push) protegidas por nome antes de existirem, tags `v*` protegidas."""
    group = api("GET", f"/groups/{GROUP}")
    project = api("POST", "/projects", {
        "name": name, "path": name, "namespace_id": group["id"], "visibility": "private",
        "initialize_with_readme": False,
    })
    pid = project["id"]
    api("PUT", f"/projects/{pid}", {
        "ci_config_path": f"pipeline.yml@{GROUP}/ci-templates", "merge_method": "merge",
        "squash_option": "never", "only_allow_merge_if_pipeline_succeeds": True,
    })
    api("POST", f"/projects/{pid}/protected_branches", {"name": "main", "push_access_level": 0, "merge_access_level": 30})
    api("POST", f"/projects/{pid}/protected_branches", {"name": "homolog", "push_access_level": 40, "merge_access_level": 30})
    api("POST", f"/projects/{pid}/protected_tags", {"name": "v*", "create_access_level": 40})
    return project


def ssh_url(project: dict) -> str:
    return f"{INTERNAL_SSH}/{project['path_with_namespace']}.git"


def add_deploy_key(pid: int, public_key: str, *, can_push: bool = True, token: str = ROOT_TOKEN) -> dict:
    return api("POST", f"/projects/{pid}/deploy_keys",
               {"title": f"aidb-{time.time_ns()}", "key": public_key, "can_push": can_push}, token=token)


def branch(pid: int, name: str) -> dict | None:
    return api("GET", f"/projects/{pid}/repository/branches/{q(name)}", ok404=True)


def wait_branch(pid: int, name: str, sha: str | None = None, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = branch(pid, name)
        if found and (sha is None or found["commit"]["id"] == sha):
            return found
        time.sleep(1)
    raise AssertionError(f"branch {name} não chegou ao GitLab ({sha=})")


def bootstrap_main(pid: int) -> None:
    """Primeira vez: a `main` nasce da `homolog` enviada pelo portal (o guia de preparação
    descreve o mesmo passo) e vira a branch padrão."""
    api("POST", f"/projects/{pid}/repository/branches", {"branch": "main", "ref": "homolog"})
    api("PUT", f"/projects/{pid}", {"default_branch": "main"})


def delete_project(pid: int) -> None:
    """Arrumação no fim do teste, não verificação: o GitLab às vezes responde 500 enquanto um
    pipeline do projeto ainda roda; tenta de novo e, se não der, deixa o projeto para trás."""
    for _ in range(3):
        try:
            api("DELETE", f"/projects/{pid}", ok404=True)
            return
        except AssertionError:
            time.sleep(5)
