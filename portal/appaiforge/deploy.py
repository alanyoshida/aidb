"""Implantação de versões em sistemas só implantação (change add-deploy-only-system).

O portal lê o repositório GitLab do sistema pela cópia de retransmissão de `git_sync` (com a chave
só leitura do sistema), verifica que o commit de uma tag está contido na branch de destino, leva o
commit ao repositório do sistema e troca o workspace — dependências antes do código, saúde depois,
e volta à versão anterior quando a nova não fica saudável (design D4, D5). O portal nunca escreve
nada no repositório remoto.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import secrets as _secrets
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .git_backend import GitError, get_backend
from .models import Deployment, DeploySettings, System, SystemStatus, User
from .security import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

TRIGGER_MANUAL = "manual"
TRIGGER_POLLING = "polling"
TRIGGER_WEBHOOK = "webhook"
MODES = ("manual", "automatic")
DETECTIONS = ("polling", "webhook")
MANIFEST_PATH = ".aidb/manifest.json"
APP_PID_FILE = "/tmp/aidb-app.pid"
VENV_PATH = "/workspace/app/.venv"


class DeployError(Exception):
    """Implantação recusada ou que falhou; a mensagem vai para o histórico e para a tela."""


class NotConfigured(DeployError):
    pass


class TagNotOnTarget(DeployError):
    pass


class MissingConnections(DeployError):
    def __init__(self, names: list[str]):
        super().__init__("faltam conexões exigidas pela versão: " + ", ".join(names))
        self.names = names


class DeployBusy(DeployError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------
# Versões: listar tags do padrão em ordem de versão (design D4)
# ---------------------------------------------------------------------------------------------


def version_key(tag: str) -> tuple:
    """Ordena por versão: trechos numéricos comparados como números (`v1.0.10` > `v1.0.2`)."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.findall(r"\d+|\D+", tag))


def filter_and_sort(tags: dict[str, str], pattern: str) -> list[tuple[str, str]]:
    """Tags (nome → commit) que seguem o padrão, da mais nova para a mais antiga."""
    chosen = [(name, sha) for name, sha in tags.items() if fnmatch.fnmatchcase(name, pattern or "*")]
    return sorted(chosen, key=lambda item: version_key(item[0]), reverse=True)


def _load_secrets(system: System):
    from .services.git_remote import load_secrets

    secrets = load_secrets(system.id)
    if secrets is None:
        raise NotConfigured("configure o repositório do sistema antes de implantar")
    if not secrets.host_key:
        raise NotConfigured("teste a conexão e confirme a identidade do servidor antes de implantar")
    return secrets


def remote_tags(system: System, secrets=None) -> dict[str, str]:
    """Tags do repositório remoto (nome → commit), com as anotadas resolvidas pelo `^{}`."""
    from .git_sync import ensure_relay, relay_git

    secrets = secrets or _load_secrets(system)
    ensure_relay(system.slug)
    out = relay_git(system.slug, "ls-remote", "--tags", secrets.address.ssh_url(), secrets=secrets)
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in str(out).splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        name = parts[1][len("refs/tags/"):]
        if name.endswith("^{}"):
            peeled[name[:-3]] = parts[0]
        else:
            tags[name] = parts[0]
    tags.update({name: sha for name, sha in peeled.items() if name in tags})
    return tags


def get_deploy_settings(system_id: str) -> DeploySettings:
    with session_scope() as s:
        settings = s.get(DeploySettings, system_id)
        if settings is None:
            settings = DeploySettings(system_id=system_id)
            s.add(settings)
            s.flush()
        s.expunge(settings)
        return settings


def list_versions(system: System) -> list[dict]:
    """Versões disponíveis: tags do padrão em ordem de versão, marcando a atual e as já
    implantadas (requirement "Lista de versões disponíveis")."""
    pattern = get_deploy_settings(system.id).tag_pattern
    tags = filter_and_sort(remote_tags(system), pattern)
    current = current_deployment(system.id)
    with session_scope() as s:
        deployed = set(s.execute(select(Deployment.tag).where(Deployment.system_id == system.id)).scalars())
    return [
        {"tag": name, "sha": sha, "current": bool(current and current["tag"] == name), "deployed": name in deployed}
        for name, sha in tags
    ]


# ---------------------------------------------------------------------------------------------
# Verificação da tag e transferência do commit (design D4)
# ---------------------------------------------------------------------------------------------


def verify_and_fetch(system: System, tag: str, secrets=None) -> str:
    """Traz a branch de destino e a tag para a retransmissão, confere que o commit da tag está
    contido na branch de destino e leva o commit ao repositório do sistema. Devolve o commit
    verificado — o que a tag aponta agora, não o que apontava quando foi listada."""
    from .git_sync import _relay_has, _system_has, ensure_relay, relay_git, system_tip

    secrets = secrets or _load_secrets(system)
    slug, url, target = system.slug, secrets.address.ssh_url(), secrets.target_branch
    ensure_relay(slug)
    if not str(relay_git(slug, "ls-remote", "--tags", url, f"refs/tags/{tag}", secrets=secrets)).strip():
        raise DeployError(f"a tag {tag} não existe no repositório")
    if not str(relay_git(slug, "ls-remote", "--heads", url, f"refs/heads/{target}", secrets=secrets)).strip():
        raise DeployError(f"a branch de destino {target} não existe no repositório")
    tracking = f"refs/remotes/origin/{target}"
    relay_git(slug, "fetch", "-q", "--no-tags", url, f"+refs/heads/{target}:{tracking}",
              f"+refs/tags/{tag}:refs/aidb/tags/{tag}", secrets=secrets)
    sha = str(relay_git(slug, "rev-parse", f"refs/aidb/tags/{tag}^{{commit}}")).strip()
    try:
        relay_git(slug, "merge-base", "--is-ancestor", sha, tracking)
    except GitError:
        raise TagNotOnTarget(
            f"a versão {tag} ({sha[:8]}) não passou pela branch de destino {target}; implantação recusada"
        ) from None
    deploy_ref = f"refs/aidb/deploy/{sha}"
    if _system_has(system, sha):
        get_backend().run(system, "update-ref", deploy_ref, sha, work_tree=False)
        return sha
    relay_git(slug, "update-ref", deploy_ref, sha)
    revs = [deploy_ref]
    local = system_tip(system)
    if local and _relay_has(slug, local) and local != sha:
        revs.append(f"^{local}")
    data = relay_git(slug, "bundle", "create", "-", *revs, raw=True)
    get_backend().import_bundle(system, data, f"+{deploy_ref}:{deploy_ref}")
    return sha


# ---------------------------------------------------------------------------------------------
# Manifesto de conexões (design D8)
# ---------------------------------------------------------------------------------------------


def _env_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", name.upper())


def _git_file(system: System, sha: str | None, path: str) -> str | None:
    if not sha:
        return None
    try:
        return get_backend().run(system, "cat-file", "blob", f"{sha}:{path}", work_tree=False)
    except GitError:
        return None


def _git_object(system: System, sha: str | None, path: str) -> str | None:
    if not sha:
        return None
    try:
        return get_backend().run(system, "rev-parse", "-q", "--verify", f"{sha}:{path}", work_tree=False) or None
    except GitError:
        return None


def check_manifest(system: System, sha: str) -> str:
    """Confere as conexões exigidas pelo manifesto do commit. Levanta `MissingConnections` se
    falta alguma; devolve um aviso quando a versão não tem manifesto (e "" quando conferiu)."""
    raw = _git_file(system, sha, MANIFEST_PATH)
    if raw is None:
        return "a versão não tem manifesto de conexões; as conexões não foram conferidas"
    try:
        required = [str(c["name"]) for c in json.loads(raw).get("connections", [])]
    except (ValueError, TypeError, KeyError, AttributeError):
        return "o manifesto de conexões da versão é inválido; as conexões não foram conferidas"
    from .services.connections import active_connections

    # só conexões ativas, pelo alias (change add-db-manager-role): é o que vira variável de ambiente
    existing = {c.env_name for c in active_connections(system.id)}
    missing = [name for name in required if _env_name(name) not in existing]
    if missing:
        raise MissingConnections(missing)
    return ""


# ---------------------------------------------------------------------------------------------
# Implantação (design D5, D6)
# ---------------------------------------------------------------------------------------------


def _install_deps(system: System, sha: str, previous: str | None) -> bool:
    """`uv sync --frozen` do lock do commit, num diretório temporário do container, no ambiente da
    app. Só roda quando o lock muda. Devolve se instalou."""
    from .drivers import get_driver

    new_lock = _git_object(system, sha, "app/uv.lock")
    if new_lock is None or new_lock == _git_object(system, previous, "app/uv.lock"):
        return False
    files = {}
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        content = _git_file(system, sha, f"app/{name}")
        if content is not None:
            files[name] = (content + "\n").encode()
    if "pyproject.toml" not in files:
        raise DeployError("a versão tem app/uv.lock mas não tem app/pyproject.toml")
    driver = get_driver()
    tmp = f"/tmp/aidb-deploy-{sha[:12]}"
    try:
        driver.write_app_files(system, tmp, files)
        code, _out, err = driver.exec_in_app(
            system, ["uv", "sync", "--frozen", "--no-install-project", "--project", tmp],
            env={"UV_PROJECT_ENVIRONMENT": VENV_PATH}, timeout=600,
        )
    finally:
        try:
            driver.exec_in_app(system, ["rm", "-rf", tmp], timeout=30)
        except Exception:  # noqa: BLE001 - limpeza de melhor esforço
            log.warning("não foi possível limpar %s no sistema %s", tmp, system.slug)
    if code != 0:
        tail = "\n".join(err.strip().splitlines()[-5:])
        raise DeployError(f"a instalação das dependências falhou: {tail}")
    return True


def _checkout(system: System, sha: str) -> None:
    """Workspace com exatamente o conteúdo do commit; o ambiente da app (`.venv`) fica."""
    backend = get_backend()
    backend.add_exclude(system, ".venv/")
    backend.prepare_work_tree(system)
    backend.run(system, "reset", "-q", "--hard", sha)
    backend.run(system, "clean", "-fdq")


def _app_pid(system: System) -> str | None:
    from .drivers import get_driver

    try:
        code, out, _ = get_driver().exec_in_app(system, ["cat", APP_PID_FILE], timeout=15)
    except Exception:  # noqa: BLE001 - container reiniciando
        return None
    parts = out.split()
    return parts[0] if code == 0 and parts else None


def _wait_healthy(system: System, before_pid: str | None) -> str | None:
    """Espera a app nova responder em três checagens seguidas dentro do prazo. Com `before_pid`,
    só conta depois que o supervisor reiniciou a app. Devolve None se ficou saudável, ou o motivo."""
    from .drivers import get_driver

    settings = get_settings()
    deadline = time.monotonic() + settings.deploy_health_timeout
    driver = get_driver()
    consecutive, last_pid = 0, None
    while time.monotonic() < deadline:
        pid = _app_pid(system)
        if before_pid is not None and pid in (None, before_pid):
            time.sleep(1)
            continue
        if pid != last_pid:
            consecutive, last_pid = 0, pid
        consecutive = consecutive + 1 if driver.is_healthy(system.slug) else 0
        if consecutive >= 3:
            return None
        time.sleep(settings.deploy_health_interval)
    if before_pid is not None and _app_pid(system) in (None, before_pid):
        return f"a app não reiniciou na versão nova em {settings.deploy_health_timeout:.0f}s"
    return f"a app não ficou saudável em {settings.deploy_health_timeout:.0f}s"


def _switch(system: System, sha: str, previous: str | None) -> str | None:
    """Dependências, código e saúde. Devolve None se saudável, ou o motivo."""
    _install_deps(system, sha, previous)
    app_changed = _git_object(system, sha, "app") != _git_object(system, previous, "app")
    before_pid = _app_pid(system) if app_changed else None
    _checkout(system, sha)
    return _wait_healthy(system, before_pid)


def _finish(deployment_id: str, status: str, detail: str, **fields) -> None:
    with session_scope() as s:
        dep = s.get(Deployment, deployment_id)
        dep.status, dep.detail, dep.finished_at = status, detail, _now()
        for key, value in fields.items():
            setattr(dep, key, value)


def _view(dep: Deployment) -> dict:
    return {
        "id": dep.id, "tag": dep.tag, "commit_sha": dep.commit_sha, "trigger": dep.trigger,
        "actor_id": dep.actor_id, "status": dep.status, "detail": dep.detail,
        "previous_sha": dep.previous_sha,
        "created_at": dep.created_at.isoformat() if dep.created_at else None,
        "finished_at": dep.finished_at.isoformat() if dep.finished_at else None,
    }


def get_deployment(deployment_id: str) -> dict | None:
    with session_scope() as s:
        dep = s.get(Deployment, deployment_id)
        return _view(dep) if dep else None


def list_deployments(system_id: str, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(Deployment).where(Deployment.system_id == system_id)
            .order_by(Deployment.created_at.desc()).limit(limit)
        ).scalars()
        return [_view(d) for d in rows]


def current_deployment(system_id: str) -> dict | None:
    """A versão atual é a última implantação com sucesso (design D3)."""
    with session_scope() as s:
        dep = s.execute(
            select(Deployment).where(Deployment.system_id == system_id, Deployment.status == "succeeded")
            .order_by(Deployment.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        return _view(dep) if dep else None


def _audit(actor: User | None, system: System, view: dict) -> None:
    from .services import audit

    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="deploy.run", resource_type="deployment", resource_id=view["id"], system_id=system.id,
        details={"tag": view["tag"], "commit": view["commit_sha"], "origem": view["trigger"],
                 "resultado": view["status"], "detalhe": view["detail"]},
    )


def deploy(system: System, tag: str, *, trigger: str = TRIGGER_MANUAL, actor: User | None = None) -> dict:
    """Implanta a tag no sistema. Uma implantação (ou operação de repositório) por sistema por vez
    (design D6). Devolve o registro da implantação, inclusive quando recusada ou com falha."""
    from .git_sync import system_lock

    if system.kind != "deploy_only":
        raise DeployError("só sistemas só implantação implantam versões")
    lock = system_lock(system.id)
    if not lock.acquire(blocking=False):
        raise DeployBusy("já há uma implantação em andamento neste sistema")
    try:
        return _deploy_locked(system, tag, trigger, actor)
    finally:
        lock.release()


def _deploy_locked(system: System, tag: str, trigger: str, actor: User | None) -> dict:
    from .checkpoints import ensure_repo
    from .git_sync import RemoteError, system_tip

    with session_scope() as s:
        dep = Deployment(system_id=system.id, tag=tag, trigger=trigger,
                         actor_id=actor.id if actor else None, status="running")
        s.add(dep)
        s.flush()
        deployment_id = dep.id
    previous: str | None = None
    try:
        secrets = _load_secrets(system)
        ensure_repo(system)
        previous = system_tip(system)
        sha = verify_and_fetch(system, tag, secrets)
        with session_scope() as s:
            dep = s.get(Deployment, deployment_id)
            dep.commit_sha, dep.previous_sha = sha, previous
        if _git_object(system, sha, "app/main.py") is None:
            raise DeployError(f"a versão {tag} não tem app/main.py")
        if _git_object(system, sha, "app/uv.lock") is None and _git_object(system, sha, "app/requirements.txt") is not None:
            # a produção instala dependências só pelo uv.lock: sem ele a app subiria sem nada
            raise DeployError(f"a versão {tag} declara dependências em app/requirements.txt sem app/uv.lock; "
                              "na homologação, peça ao agente para gerenciá-las com uv (uv add) e promova de novo")
        warning = check_manifest(system, sha)
        failure = _switch(system, sha, previous)
        if failure is None:
            _finish(deployment_id, "succeeded", warning)
        elif previous:
            try:
                back = _switch(system, previous, sha)
                tail = "" if back is None else f"; a versão anterior também não respondeu: {back}"
            except (DeployError, GitError, RemoteError) as exc:
                tail = f"; a volta à versão anterior falhou: {exc}"
            _finish(deployment_id, "rolled_back", f"{failure}; voltou para {previous[:8]}{tail}")
        else:
            _finish(deployment_id, "failed", failure)
    except (DeployError, GitError, RemoteError) as exc:
        _finish(deployment_id, "failed", str(exc))
    except Exception as exc:  # noqa: BLE001 - registra e repassa
        _finish(deployment_id, "failed", f"erro inesperado: {exc}")
        raise
    view = get_deployment(deployment_id)
    _audit(actor, system, view)
    log.info("implantação %s de %s em %s: %s", deployment_id, tag, system.slug, view["status"])
    return view


def recover_interrupted() -> None:
    """Na subida do portal: implantação `running` vira `failed` ("interrompida") e o workspace
    volta ao commit da última implantação com sucesso (design D6)."""
    from .services.systems import get_system

    with session_scope() as s:
        rows = s.execute(select(Deployment).where(Deployment.status == "running")).scalars().all()
        stuck = [(d.id, d.system_id) for d in rows]
    for deployment_id, system_id in stuck:
        _finish(deployment_id, "failed", "interrompida: o portal reiniciou durante a implantação")
        current = current_deployment(system_id)
        system = get_system(system_id)
        if current is None or system is None:
            continue
        try:
            if get_backend().run(system, "rev-parse", "HEAD", work_tree=False) != current["commit_sha"]:
                _checkout(system, current["commit_sha"])
        except GitError:
            log.exception("não foi possível restaurar o workspace de %s após implantação interrompida", system.slug)


# ---------------------------------------------------------------------------------------------
# Modo automático, consulta periódica e webhook (design D7)
# ---------------------------------------------------------------------------------------------


def newest_undeployed(system: System, tags: dict[str, str], pattern: str) -> str | None:
    """A regra do automático: a tag mais nova do padrão, só se nunca implantada (com qualquer
    resultado) neste sistema."""
    ordered = filter_and_sort(tags, pattern)
    if not ordered:
        return None
    newest = ordered[0][0]
    with session_scope() as s:
        seen = s.execute(
            select(Deployment.id).where(Deployment.system_id == system.id, Deployment.tag == newest).limit(1)
        ).scalar_one_or_none()
    return None if seen else newest


def check_for_new(system: System, trigger: str) -> dict | None:
    """Uma verificação do automático: implanta a tag nova, se houver. Modo manual não implanta."""
    settings = get_deploy_settings(system.id)
    if settings.mode != "automatic":
        return None
    with session_scope() as s:
        row = s.get(DeploySettings, system.id)
        row.last_checked_at = _now()
    tag = newest_undeployed(system, remote_tags(system), settings.tag_pattern)
    if tag is None:
        return None
    try:
        return deploy(system, tag, trigger=trigger)
    except DeployBusy:
        return None


def _auto_systems(detection: str) -> list[System]:
    with session_scope() as s:
        rows = s.execute(
            select(System).join(DeploySettings, DeploySettings.system_id == System.id).where(
                System.kind == "deploy_only", System.status == SystemStatus.active,
                DeploySettings.mode == "automatic", DeploySettings.detection == detection,
            )
        ).scalars().all()
        for row in rows:
            s.expunge(row)
        return list(rows)


def poll_once() -> None:
    for system in _auto_systems("polling"):
        try:
            check_for_new(system, TRIGGER_POLLING)
        except Exception:  # noqa: BLE001 - um sistema não derruba a consulta dos outros
            log.exception("consulta de versões falhou para %s", system.slug)


def start_poller(interval: float | None = None, stop: threading.Event | None = None) -> threading.Thread:
    seconds = interval if interval is not None else get_settings().deploy_poll_interval
    stop = stop or threading.Event()

    def loop() -> None:
        while not stop.wait(seconds):
            try:
                poll_once()
            except Exception:  # noqa: BLE001
                log.exception("consulta periódica de versões falhou")

    thread = threading.Thread(target=loop, daemon=True, name="deploy-poller")
    thread.start()
    return thread


def webhook_check(system_id: str) -> None:
    """Verificação disparada por webhook válido, em segundo plano. O corpo da chamada nunca
    chega aqui: só o repositório decide o que implantar."""
    from .services.systems import get_system

    system = get_system(system_id)
    if system is None or system.kind != "deploy_only" or system.status != SystemStatus.active:
        return
    if get_deploy_settings(system_id).detection != "webhook":
        return
    try:
        check_for_new(system, TRIGGER_WEBHOOK)
    except Exception:  # noqa: BLE001
        log.exception("verificação por webhook falhou para %s", system.slug)


def schedule_webhook_check(system_id: str) -> None:
    threading.Thread(target=webhook_check, args=(system_id,), daemon=True, name=f"deploy-hook-{system_id}").start()


def webhook_secret(system_id: str) -> str:
    """Segredo do webhook do sistema, gerado na primeira leitura (exibido na aba Implantação)."""
    with session_scope() as s:
        row = s.get(DeploySettings, system_id)
        if row is None:
            row = DeploySettings(system_id=system_id)
            s.add(row)
        if not row.webhook_secret_encrypted:
            row.webhook_secret_encrypted = encrypt_secret(_secrets.token_urlsafe(32))
        s.flush()
        return decrypt_secret(row.webhook_secret_encrypted)


def rotate_webhook_secret(system: System, actor: User) -> str:
    from .services import audit

    _require_manager(actor, system)
    with session_scope() as s:
        row = s.get(DeploySettings, system.id)
        if row is None:
            row = DeploySettings(system_id=system.id)
            s.add(row)
        row.webhook_secret_encrypted = encrypt_secret(_secrets.token_urlsafe(32))
    audit.record(actor_id=actor.id, actor_email=actor.email, action="deploy.webhook_rotate",
                 resource_type="deploy_settings", resource_id=system.id, system_id=system.id, details={})
    return webhook_secret(system.id)


def matches_webhook_secret(system_id: str, supplied: str) -> bool:
    import hmac

    with session_scope() as s:
        row = s.get(DeploySettings, system_id)
        stored = row.webhook_secret_encrypted if row else None
    if not stored or not supplied:
        hmac.compare_digest("x", "y")
        return False
    return hmac.compare_digest(decrypt_secret(stored).encode(), supplied.encode())


def _require_manager(user: User, system: System) -> None:
    from .rbac import can_manage_system

    if not can_manage_system(user, system):
        raise DeployError("somente o dono do sistema ou um admin gerenciam a implantação")


def update_settings(system: System, actor: User, *, tag_pattern: str, mode: str, detection: str) -> None:
    from .services import audit

    _require_manager(actor, system)
    tag_pattern = (tag_pattern or "v*").strip()
    if not tag_pattern or any(ch.isspace() for ch in tag_pattern) or len(tag_pattern) > 100:
        raise DeployError("padrão de tags inválido")
    if mode not in MODES or detection not in DETECTIONS:
        raise DeployError("modo ou detecção inválidos")
    with session_scope() as s:
        row = s.get(DeploySettings, system.id)
        if row is None:
            row = DeploySettings(system_id=system.id)
            s.add(row)
        row.tag_pattern, row.mode, row.detection = tag_pattern, mode, detection
    audit.record(actor_id=actor.id, actor_email=actor.email, action="deploy.settings",
                 resource_type="deploy_settings", resource_id=system.id, system_id=system.id,
                 details={"padrao": tag_pattern, "modo": mode, "deteccao": detection})


def deploy_by_user(system: System, actor: User, tag: str) -> dict:
    _require_manager(actor, system)
    return deploy(system, tag, trigger=TRIGGER_MANUAL, actor=actor)
