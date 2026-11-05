"""Checkpoints git por sistema (ADR 0009; spec agent-harness).

Git no volume do workspace; commit ao fim de run bem-sucedida; rollback com
`git reset --hard` + clean (o supervisor detecta a mudança e reinicia a app).
"""

import logging
import os
import subprocess

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import Checkpoint, System, User
from .services import audit

log = logging.getLogger(__name__)


class GitError(Exception):
    pass


def workspace_dir(system: System) -> str:
    return os.path.join(get_settings().workspaces_dir, system.slug)


def _git(system: System, *args: str) -> str:
    cwd = workspace_dir(system)
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])}: {result.stderr.strip()}")
    return result.stdout.strip()


def ensure_repo(system: System) -> None:
    """git init idempotente + user do commit configurado."""
    ensure = workspace_dir(system)
    os.makedirs(ensure, exist_ok=True)
    # git recusa operar num diretório cujo dono não é o uid que roda o comando
    # ("dubious ownership") — o portal roda git como root (checkpoints.py), mas
    # o workspace de um sistema em modo de execução reduzido (ADR 0018) pertence
    # ao usuário do agente, não a root. O portal é o único processo que gerencia
    # esses repositórios, então confia em todos — não é exposição nova.
    subprocess.run(
        ["git", "config", "--global", "--replace-all", "safe.directory", "*"],
        capture_output=True, text=True, timeout=10,
    )
    if not os.path.isdir(os.path.join(ensure, ".git")):
        _git(system, "init", "-q", "-b", "main")
    _git(system, "config", "user.email", "appaiforge@portal")
    _git(system, "config", "user.name", "AIDB")


def commit_all(system: System, message: str, author: User | None = None) -> str | None:
    """Commita tudo; devolve o sha ou None se nada mudou."""
    ensure_repo(system)
    _git(system, "add", "-A")
    status = _git(system, "status", "--porcelain")
    if not status:
        return None
    name = author.email if author else "appaiforge@portal"
    _git(system, "-c", f"user.name={name}", "-c", f"user.email={name}", "commit", "-q", "-m", message)
    sha = _git(system, "rev-parse", "HEAD")
    return sha


def record_checkpoint(system: System, run_id: str | None, message: str, author: User | None = None) -> Checkpoint | None:
    sha = commit_all(system, message, author)
    if sha is None:
        return None
    with session_scope() as s:
        cp = Checkpoint(
            system_id=system.id, run_id=run_id, git_sha=sha, message=message,
            author_id=author.id if author else system.owner_id,
            author_email=author.email if author else "",
        )
        s.add(cp)
        s.flush()
        s.expunge(cp)
    audit.record(
        actor_id=author.id if author else None, actor_email=author.email if author else None,
        action="checkpoint.create", resource_type="checkpoint",
        resource_id=cp.id, system_id=system.id, details={"git_sha": sha[:8]},
    )
    return cp


def delete_checkpoint(system: System, checkpoint_id: str, actor: User | None = None) -> None:
    """Remove um checkpoint do histórico (não mexe no workspace atual)."""
    with session_scope() as s:
        cp = s.get(Checkpoint, checkpoint_id)
        if cp is None or cp.system_id != system.id:
            return
        s.delete(cp)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="checkpoint.delete", resource_type="checkpoint",
        resource_id=checkpoint_id, system_id=system.id, details={},
    )
    log.info("checkpoint removido: sistema=%s id=%s", system.slug, checkpoint_id)


def list_checkpoints(system: System) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(select(Checkpoint).where(Checkpoint.system_id == system.id).order_by(Checkpoint.created_at.desc())).scalars().all()
        return [{"id": r.id, "git_sha": r.git_sha, "message": r.message, "created_at": r.created_at.isoformat()} for r in rows]


def rollback(system: System, git_sha: str) -> None:
    """Volta o workspace ao checkpoint (reset --hard + clean) e registra."""
    ensure_repo(system)
    _git(system, "reset", "--hard", git_sha)
    _git(system, "clean", "-fd")
    log.info("rollback do sistema %s para %s", system.slug, git_sha)
