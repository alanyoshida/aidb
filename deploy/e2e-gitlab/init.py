#!/usr/bin/env python3
"""Prepara o GitLab da stack E2E (change add-system-git-remote). Idempotente.

    python3 deploy/e2e-gitlab/init.py

- token de API do root com valor fixo de teste (`ROOT_TOKEN`);
- runner de instância com executor shell, registrado no container gitlab-runner;
- grupo `aidb`, projeto `aidb/ci-templates` com `pipeline.yml`;
- projeto `aidb/sistema-e2e`: README na `main`, branch `homolog`, config de CI apontando para
  `pipeline.yml@aidb/ci-templates`, merge commit sem squash, merge só com pipeline verde,
  `main` protegida (ninguém faz push, developers fazem merge), `homolog` protegida
  (maintainers fazem push, developers fazem merge), tags `v*` protegidas;
- token de projeto `RELEASE_TOKEN` (variável de CI mascarada), usado pelo job que cria a tag.

Credenciais e tokens daqui valem só para esta stack de teste.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("AIDB_E2E_GITLAB_API", "http://localhost:8929/api/v4")
GITLAB_CONTAINER = os.environ.get("AIDB_E2E_GITLAB_CONTAINER", "appaiforge-e2e-gitlab-gitlab-1")
RUNNER_CONTAINER = os.environ.get("AIDB_E2E_GITLAB_RUNNER_CONTAINER", "appaiforge-e2e-gitlab-gitlab-runner-1")
ROOT_TOKEN = "aidb-e2e-root-somente-local-0001"
RELEASE_TOKEN = "aidb-e2e-release-somente-local-01"
GROUP = "aidb"
TEMPLATES = "ci-templates"
SYSTEM = "sistema-e2e"
PIPELINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.yml")


def log(msg: str) -> None:
    print(f"[e2e-gitlab] {msg}", flush=True)


def api(method: str, path: str, data: dict | None = None, *, ok404: bool = False, raw: bool = False):
    body = None
    headers = {"PRIVATE-TOKEN": ROOT_TOKEN}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
            if raw:
                return content.decode()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as exc:
        if ok404 and exc.code == 404:
            return None
        raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode(errors='replace')[:300]}") from None


def wait_api() -> None:
    for _ in range(90):
        try:
            urllib.request.urlopen(API + "/version", timeout=5)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return
        except OSError:
            pass
        time.sleep(5)
    sys.exit("GitLab não respondeu em 7,5 minutos")


def rails(script: str) -> None:
    subprocess.run(["docker", "exec", GITLAB_CONTAINER, "gitlab-rails", "runner", script], check=True)


def ensure_root_token() -> None:
    try:
        api("GET", "/user")
        return
    except RuntimeError:
        pass
    log("criando o token do root (gitlab-rails runner, leva ~1 min)")
    rails(
        "u = User.find_by_username('root'); "
        "t = u.personal_access_tokens.create!(scopes: ['api', 'admin_mode', 'sudo'], "
        "name: 'aidb-e2e', expires_at: 365.days.from_now); "
        f"t.set_token('{ROOT_TOKEN}'); t.save!"
    )
    api("GET", "/user")


def ensure_runner() -> None:
    listed = subprocess.run(["docker", "exec", RUNNER_CONTAINER, "gitlab-runner", "list"],
                            capture_output=True, text=True).stderr
    if "aidb-e2e" in listed:
        return
    log("registrando o runner (executor shell)")
    runner = api("POST", "/user/runners", {"runner_type": "instance_type", "run_untagged": True,
                                           "description": "aidb-e2e"})
    subprocess.run([
        "docker", "exec", RUNNER_CONTAINER, "gitlab-runner", "register", "--non-interactive",
        "--url", "http://gitlab", "--token", runner["token"], "--executor", "shell", "--name", "aidb-e2e",
    ], check=True, capture_output=True)


def ensure_group() -> dict:
    group = api("GET", f"/groups/{GROUP}", ok404=True)
    if group is None:
        log(f"criando o grupo {GROUP}")
        group = api("POST", "/groups", {"name": GROUP, "path": GROUP, "visibility": "internal"})
    return group


def project(path: str) -> dict | None:
    return api("GET", "/projects/" + urllib.parse.quote(f"{GROUP}/{path}", safe=""), ok404=True)


def ensure_templates(group: dict) -> None:
    proj = project(TEMPLATES)
    if proj is None:
        log(f"criando {GROUP}/{TEMPLATES}")
        proj = api("POST", "/projects", {"name": TEMPLATES, "path": TEMPLATES, "namespace_id": group["id"],
                                         "visibility": "internal", "initialize_with_readme": True,
                                         "default_branch": "main"})
    with open(PIPELINE_FILE) as f:
        content = f.read()
    current = api("GET", f"/projects/{proj['id']}/repository/files/pipeline.yml/raw?ref=main",
                  ok404=True, raw=True)
    payload = {"branch": "main", "content": content, "commit_message": "Atualiza o pipeline dos sistemas"}
    if current is None:
        api("POST", f"/projects/{proj['id']}/repository/files/pipeline.yml", payload)
    elif current != content:
        api("PUT", f"/projects/{proj['id']}/repository/files/pipeline.yml", payload)


def protect(pid: int, branch: str, push: int, merge: int) -> None:
    api("DELETE", f"/projects/{pid}/protected_branches/{branch}", ok404=True)
    api("POST", f"/projects/{pid}/protected_branches",
        {"name": branch, "push_access_level": push, "merge_access_level": merge})


def ensure_system(group: dict) -> dict:
    proj = project(SYSTEM)
    if proj is None:
        log(f"criando {GROUP}/{SYSTEM}")
        proj = api("POST", "/projects", {"name": SYSTEM, "path": SYSTEM, "namespace_id": group["id"],
                                         "visibility": "private", "initialize_with_readme": True,
                                         "default_branch": "main"})
    pid = proj["id"]
    api("PUT", f"/projects/{pid}", {
        "ci_config_path": f"pipeline.yml@{GROUP}/{TEMPLATES}",
        "merge_method": "merge",
        "squash_option": "never",
        "only_allow_merge_if_pipeline_succeeds": True,
        "remove_source_branch_after_merge": False,
    })
    if api("GET", f"/projects/{pid}/repository/branches/homolog", ok404=True) is None:
        api("POST", f"/projects/{pid}/repository/branches", {"branch": "homolog", "ref": "main"})
    protect(pid, "main", 0, 30)
    protect(pid, "homolog", 40, 30)
    api("DELETE", f"/projects/{pid}/protected_tags/v*", ok404=True)
    api("POST", f"/projects/{pid}/protected_tags", {"name": "v*", "create_access_level": 40})
    return proj


def ensure_release_token(pid: int) -> None:
    if api("GET", f"/projects/{pid}/variables/RELEASE_TOKEN", ok404=True) is not None:
        return
    log("criando o token de projeto usado pelo job de release")
    rails(
        f"p = Project.find({pid}); "
        "bot = Users::CreateService.new(nil, name: 'aidb-release', username: \"project_#{p.id}_bot_aidb\", "
        "email: \"project_#{p.id}_bot_aidb@noreply.gitlab\", user_type: :project_bot, "
        "skip_confirmation: true, organization_id: p.organization_id).execute.payload[:user]; "
        "p.add_member(bot, :maintainer); "
        "t = bot.personal_access_tokens.create!(scopes: ['api'], name: 'release', expires_at: 365.days.from_now); "
        f"t.set_token('{RELEASE_TOKEN}'); t.save!"
    )
    api("POST", f"/projects/{pid}/variables",
        {"key": "RELEASE_TOKEN", "value": RELEASE_TOKEN, "masked": True, "protected": True})


def main() -> None:
    wait_api()
    ensure_root_token()
    ensure_runner()
    group = ensure_group()
    ensure_templates(group)
    system = ensure_system(group)
    ensure_release_token(system["id"])
    log(f"pronto: {API.removesuffix('/api/v4')}/{GROUP}/{SYSTEM} (token do root: {ROOT_TOKEN})")


if __name__ == "__main__":
    main()
