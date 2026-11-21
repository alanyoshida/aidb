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


def commit_file(pid: int, branch_name: str, path: str, content: str, message: str) -> str:
    """Commit direto numa branch pela API (o root pode empurrar na homolog protegida)."""
    exists = api("GET", f"/projects/{pid}/repository/files/{q(path)}?ref={q(branch_name)}", ok404=True)
    method = "PUT" if exists else "POST"
    api(method, f"/projects/{pid}/repository/files/{q(path)}",
        {"branch": branch_name, "content": content, "commit_message": message})
    return branch(pid, branch_name)["commit"]["id"]


def wait_pipeline(pid: int, sha: str, timeout: float = 480) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pipelines = api("GET", f"/projects/{pid}/pipelines?sha={sha}&per_page=5")
        for p in pipelines:
            if p["status"] in ("success", "failed", "canceled"):
                return p
        time.sleep(3)
    raise AssertionError(f"pipeline do commit {sha[:8]} não terminou")


def human_merge_request(pid: int, target: str, path: str, content: str, title: str) -> dict:
    """Um merge request humano completo: branch nova, commit, MR, pipeline verde e merge."""
    source = f"humano-{time.time_ns()}"
    api("POST", f"/projects/{pid}/repository/branches", {"branch": source, "ref": target})
    sha = commit_file(pid, source, path, content, title)
    mr = api("POST", f"/projects/{pid}/merge_requests",
             {"source_branch": source, "target_branch": target, "title": title, "remove_source_branch": True})
    return merge_when_green(pid, mr["iid"], sha)


def merge_when_green(pid: int, iid: int, sha: str | None = None, timeout: float = 480) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        mr = api("GET", f"/projects/{pid}/merge_requests/{iid}")
        pipeline = mr.get("head_pipeline")
        if pipeline and pipeline["status"] == "success" and mr.get("detailed_merge_status") in ("mergeable", "can_be_merged", None):
            return api("PUT", f"/projects/{pid}/merge_requests/{iid}/merge", {})
        if pipeline and pipeline["status"] in ("failed", "canceled"):
            raise AssertionError(f"pipeline do MR !{iid} terminou {pipeline['status']}")
        time.sleep(3)
    raise AssertionError(f"MR !{iid} não ficou pronto para merge")


def project_token(pid: int, access_level: int = 30) -> str:
    """Token de projeto (papel Developer por padrão, escopo api), como o guia recomenda."""
    expires = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 30 * 86400))
    token = api("POST", f"/projects/{pid}/access_tokens",
                {"name": "aidb-promocao", "scopes": ["api"], "access_level": access_level, "expires_at": expires})["token"]
    # o token recém-criado leva um instante para enxergar o projeto; um usuário real o cola no
    # portal depois de criá-lo na tela do GitLab
    deadline = time.time() + 60
    while time.time() < deadline:
        if api("GET", f"/projects/{pid}", token=token, ok404=True) is not None:
            return token
        time.sleep(2)
    raise AssertionError("o token de projeto não passou a enxergar o projeto")


def open_mrs(pid: int, source: str = "homolog", target: str = "main") -> list[dict]:
    return api("GET", f"/projects/{pid}/merge_requests?state=opened&source_branch={source}&target_branch={target}")


def wait_tag(pid: int, sha: str, timeout: float = 480) -> dict:
    """Tag criada pelo pipeline da main para o commit `sha` (pode já haver tags de pipelines
    anteriores, como o da criação da main)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for tag in api("GET", f"/projects/{pid}/repository/tags"):
            if tag["commit"]["id"] == sha:
                return tag
        time.sleep(3)
    raise AssertionError(f"nenhuma tag criada pelo pipeline da main para {sha[:8]}")
