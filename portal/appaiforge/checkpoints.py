"""Checkpoints git por sistema (ADR 0009; spec agent-harness; capability workspace-repository).

O repositório de cada sistema vive FORA do workspace (change `isolate-workspace-repository`):
o workspace é só a árvore de trabalho, e toda operação git passa por `git_backend`, que nunca
lê nem executa nada que o agente tenha escrito. Commit ao fim de run bem-sucedida; rollback
volta a árvore de trabalho ao checkpoint (o supervisor detecta a mudança e reinicia a app).
"""

import logging
import os

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .git_backend import REPO_CONFIG, GitError, get_backend
from .models import Checkpoint, System, User
from .services import audit

log = logging.getLogger(__name__)

__all__ = ["GitError"]


def workspace_dir(system: System) -> str:
    """Caminho do workspace visível ao PRÓPRIO processo do portal — só existe de verdade sob o
    driver Docker (bind mount compartilhado). Não usar para montar comandos sob o driver
    Kubernetes; `_git` já trata isso internamente (change `add-kubernetes-driver`, task 8.3).
    Mesma ressalva vale para `guidelines.materialize()` e `provisioning.delete_system()` (change
    `fix-k8s-workspace-materialize-delete`): sob o driver Kubernetes, eles escrevem/removem via
    `drivers.kubernetes_driver.write_workspace_files()`/`delete_workspace_pvc()`, nunca por este
    caminho."""
    return os.path.join(get_settings().workspaces_dir, system.slug)


def _git(system: System, *args: str) -> str:
    return get_backend().run(system, *args)


def _latest_recorded_sha(system: System) -> list[str]:
    with session_scope() as s:
        rows = s.execute(
            select(Checkpoint.git_sha)
            .where(Checkpoint.system_id == system.id)
            .order_by(Checkpoint.created_at.desc())
        ).scalars().all()
    return list(rows)


def ensure_repo(system: System) -> None:
    """Cria o repositório do sistema fora do workspace, se ainda não existir (idempotente).

    Para sistemas anteriores à mudança de local (design D4), o histórico é trazido do `.git`
    antigo do workspace copiando só os arquivos de objeto, como dado; a branch passa a apontar
    para o último checkpoint REGISTRADO pelo portal — nunca para o que as refs do `.git` antigo
    dizem, que o agente pode ter alterado. O `.git` antigo fica no workspace, intocado e sem uso.
    """
    backend = get_backend()
    if backend.is_initialized(system):
        return
    backend.create(system)
    backend.run(system, "init", "-q", "--template=", "-b", "main", work_tree=False)
    for key, value in REPO_CONFIG:
        backend.run(system, "config", key, value, work_tree=False)
    backend.import_legacy_objects(system)
    backend.prepare_work_tree(system)
    for sha in _latest_recorded_sha(system):
        try:
            backend.run(system, "cat-file", "-e", f"{sha}^{{commit}}", work_tree=False)
        except GitError:
            continue
        backend.run(system, "update-ref", "refs/heads/main", sha, work_tree=False)
        backend.run(system, "read-tree", sha)
        log.info("histórico do sistema %s migrado para fora do workspace em %s", system.slug, sha[:8])
        break


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


# Origens de um checkpoint (coluna `checkpoints.origin`, change isolate-workspace-repository).
ORIGIN_RUN = "run"
ORIGIN_MANUAL = "manual"
ORIGIN_RESTORE = "restore"


def record_checkpoint(
    system: System, run_id: str | None, message: str, author: User | None = None, origin: str = ORIGIN_RUN,
) -> Checkpoint | None:
    sha = commit_all(system, message, author)
    if sha is None:
        return None
    with session_scope() as s:
        cp = Checkpoint(
            system_id=system.id, run_id=run_id, git_sha=sha, message=message,
            author_id=author.id if author else system.owner_id,
            author_email=author.email if author else "",
            origin=origin,
        )
        s.add(cp)
        s.flush()
        s.expunge(cp)
    audit.record(
        actor_id=author.id if author else None, actor_email=author.email if author else None,
        action="checkpoint.create", resource_type="checkpoint",
        resource_id=cp.id, system_id=system.id, details={"git_sha": sha[:8], "origin": origin},
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
        return [
            {"id": r.id, "git_sha": r.git_sha, "message": r.message, "origin": r.origin,
             "created_at": r.created_at.isoformat()}
            for r in rows
        ]


def rollback(system: System, git_sha: str, author: User | None = None) -> Checkpoint | None:
    """Restaura o workspace ao estado do checkpoint `git_sha` SEM reescrever o histórico
    (change isolate-workspace-repository, design D5; spec agent-harness).

    A restauração vira um checkpoint novo (`origin = restore`) sobre a ponta atual: os
    checkpoints posteriores ao restaurado continuam no histórico e continuam restauráveis.
    Alterações ainda sem checkpoint no workspace são descartadas, como antes.

    Devolve o checkpoint de restauração, ou `None` quando não havia nada a restaurar — o
    workspace já correspondia àquele checkpoint."""
    ensure_repo(system)
    target_tree = _git(system, "rev-parse", f"{git_sha}^{{tree}}")
    head = _git(system, "rev-parse", "HEAD")
    if target_tree == _git(system, "rev-parse", "HEAD^{tree}") and not _git(system, "status", "--porcelain"):
        return None
    # Índice e árvore de trabalho no estado do checkpoint, inclusive removendo o que não existe
    # nele; depois a branch volta à ponta anterior sem tocar em arquivo nenhum, e a diferença
    # vira o commit de restauração.
    get_backend().prepare_work_tree(system)
    try:
        _git(system, "reset", "-q", "--hard", git_sha)
        _git(system, "clean", "-fdq")
    except GitError:
        # Falha no meio (ex.: arquivo que o git não consegue remover): a branch não pode ficar no
        # checkpoint antigo, ou os posteriores somem da ponta. Volta a branch e, no melhor
        # esforço, a árvore de trabalho ao estado anterior à tentativa.
        _git(system, "update-ref", "refs/heads/main", head)
        try:
            _git(system, "reset", "-q", "--hard", head)
        except GitError:
            log.exception("restauração do sistema %s falhou e a árvore de trabalho ficou parcial", system.slug)
        raise
    _git(system, "reset", "-q", "--soft", head)
    log.info("rollback do sistema %s para %s", system.slug, git_sha)
    return record_checkpoint(
        system, None, f"restaura checkpoint {git_sha[:8]}", author, origin=ORIGIN_RESTORE,
    )
