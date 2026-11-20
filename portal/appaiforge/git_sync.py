"""Conversa do portal com o repositório remoto de cada sistema (change add-system-git-remote,
design D1-D2).

Tudo daqui roda no processo do portal, nunca no container do sistema: a chave privada só existe
num diretório temporário durante a operação, e o git fala com o remoto a partir de uma cópia bare
de retransmissão (`<git_relays_dir>/<slug>`), que troca pacotes com o repositório do sistema.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Iterator

from .config import get_settings
import threading

from .git_backend import BUNDLE_FETCH_OPTIONS, SAFE_OPTIONS, GitError, get_backend, git_env
from .models import System, User
from .services.git_remote import RemoteAddress, RemoteSecrets

REMOTE_TIMEOUT = 30


class RemoteError(GitError):
    """Falha ao falar com o remoto; `kind` diz o motivo para a interface."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # error | access_denied | host_key_changed | unreachable | rejected


def _secret_dir() -> str:
    base = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
    return tempfile.mkdtemp(prefix="aidb-ssh-", dir=base)


def known_hosts_line(address: RemoteAddress, host_key: str) -> str:
    host = address.host if not address.port or address.port == 22 else f"[{address.host}]:{address.port}"
    return "\n".join(f"{host} {line.strip()}" for line in host_key.splitlines() if line.strip()) + "\n"


@contextlib.contextmanager
def ssh_env(secrets: RemoteSecrets, *, host_key: str | None = None) -> Iterator[dict[str, str]]:
    """Ambiente com GIT_SSH_COMMAND apontando para a chave e o known_hosts temporários; tudo é
    apagado ao sair, com sucesso ou erro."""
    directory = _secret_dir()
    try:
        os.chmod(directory, 0o700)
        key_path = os.path.join(directory, "id")
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.private_key if secrets.private_key.endswith("\n") else secrets.private_key + "\n")
        known = os.path.join(directory, "known_hosts")
        with open(known, "w") as f:
            confirmed = host_key if host_key is not None else secrets.host_key
            if confirmed:
                f.write(known_hosts_line(secrets.address, confirmed))
        ssh = (
            f"ssh -F /dev/null -i {key_path} -o IdentitiesOnly=yes -o BatchMode=yes"
            f" -o StrictHostKeyChecking=yes -o UserKnownHostsFile={known}"
            f" -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=15"
        )
        yield {"GIT_SSH_COMMAND": ssh, "GIT_ALLOW_PROTOCOL": "ssh"}
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _classify(stderr: str) -> RemoteError:
    text = stderr.strip()
    lowered = text.lower()
    if "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        return RemoteError("a identidade do servidor mudou desde a confirmação; nada foi enviado nem recebido",
                           "host_key_changed")
    if "permission denied" in lowered or "access denied" in lowered or "not allowed to push" in lowered:
        return RemoteError(f"acesso negado pelo repositório remoto: {text[-300:]}", "access_denied")
    if any(s in lowered for s in ("could not resolve", "connection refused", "timed out", "no route", "connection closed")):
        return RemoteError(f"repositório remoto inacessível: {text[-300:]}", "unreachable")
    if "rejected" in lowered or "non-fast-forward" in lowered or "pre-receive hook declined" in lowered:
        return RemoteError(f"o remoto recusou o envio: {text[-300:]}", "rejected")
    return RemoteError(f"erro ao falar com o remoto: {text[-300:]}")


def relay_dir(slug: str) -> str:
    return os.path.join(get_settings().git_relays_dir, slug)


def ensure_relay(slug: str) -> str:
    """Cópia bare de retransmissão do sistema (cache reconstruível, só do portal)."""
    path = relay_dir(slug)
    if not os.path.isfile(os.path.join(path, "HEAD")):
        os.makedirs(path, exist_ok=True)
        relay_git(slug, "init", "-q", "--bare", "--template=")
    return path


def relay_git(slug: str, *args: str, secrets: RemoteSecrets | None = None, host_key: str | None = None,
              stdin: bytes | None = None, timeout: int = REMOTE_TIMEOUT, raw: bool = False,
              options: tuple[str, ...] = ()) -> str | bytes:
    """git na cópia de retransmissão. Com `secrets`, pode falar com o remoto por SSH (e só SSH)."""
    path = relay_dir(slug)
    env = git_env(path, None)
    extra: tuple[str, ...] = options
    with contextlib.ExitStack() as stack:
        if secrets is not None:
            env.update(stack.enter_context(ssh_env(secrets, host_key=host_key)))
            extra = (*extra, "-c", "protocol.ssh.allow=always")
        try:
            result = subprocess.run(
                ["git", *SAFE_OPTIONS, *extra, *args], cwd=path, env=env, input=stdin,
                capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RemoteError(f"o repositório remoto não respondeu em {timeout}s", "unreachable") from None
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        if secrets is not None:
            raise _classify(stderr)
        raise GitError(f"git {' '.join(args[:2])}: {stderr.strip()}")
    return result.stdout if raw else result.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------------------------
# Identidade do servidor e teste de conexão (design D2; requirements "Identidade do servidor
# remoto confirmada" e "Teste de conexão")
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostKey:
    key: str  # linhas "tipo base64", sem o host
    fingerprints: list[str]


def scan_host_key(address: RemoteAddress) -> HostKey:
    """Lê a chave apresentada pelo servidor, sem gravar nada."""
    cmd = ["ssh-keyscan", "-T", "10", "-t", "ed25519,ecdsa,rsa"]
    if address.port:
        cmd += ["-p", str(address.port)]
    cmd.append(address.host)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=REMOTE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RemoteError("o servidor não respondeu à leitura da chave", "unreachable") from None
    lines = [" ".join(line.split()[1:3]) for line in result.stdout.splitlines()
             if line.strip() and not line.startswith("#") and len(line.split()) >= 3]
    if not lines:
        raise RemoteError(f"não foi possível ler a chave do servidor {address.host}", "unreachable")
    fingerprints = []
    for line in lines:
        fp = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", "-"], input=f"x {line}\n",
                            capture_output=True, text=True)
        if fp.returncode == 0:
            fingerprints.append(" ".join(fp.stdout.split()[1:2] + fp.stdout.split()[-1:]))
    return HostKey(key="\n".join(lines), fingerprints=fingerprints)


def check_access(slug: str, secrets: RemoteSecrets) -> list[str]:
    """`git ls-remote` com a chave do sistema e a identidade confirmada; devolve as branches do
    remoto. Não escreve nada no remoto nem no workspace."""
    if not secrets.host_key:
        raise RemoteError("confirme a identidade do servidor antes de testar", "host_key_changed")
    ensure_relay(slug)
    out = relay_git(slug, "ls-remote", "--heads", secrets.address.ssh_url(), secrets=secrets)
    return [line.split("refs/heads/", 1)[1] for line in out.splitlines() if "refs/heads/" in line]


# ---------------------------------------------------------------------------------------------
# Envio e recebimento (design D1, D6; requirements "Envio de cada checkpoint à branch de
# trabalho" e "Vínculo inicial com o repositório remoto")
# ---------------------------------------------------------------------------------------------

LOCAL_BRANCH = "main"  # branch do repositório do sistema (checkpoints)
_RELAY_LOCAL = "refs/heads/aidb-local"


class NeedsSync(RemoteError):
    """O remoto tem commits que o sistema ainda não tem: integrar antes de enviar."""

    def __init__(self, message: str = "o repositório remoto tem alterações que ainda não estão no sistema"):
        super().__init__(message, "needs_sync")


class UnrelatedHistory(RemoteError):
    def __init__(self, branch: str):
        super().__init__(f"a branch {branch} do remoto tem histórico sem relação com o do sistema", "unrelated")


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def system_lock(system_id: str) -> threading.Lock:
    """Serializa as operações de remoto de um sistema (aba Repositório e fila do agente)."""
    with _locks_guard:
        return _locks.setdefault(system_id, threading.Lock())


def remote_ref(branch: str) -> str:
    """Onde o repositório do sistema guarda a última versão conhecida da branch remota."""
    return f"refs/aidb/remote/{branch}"


def _system_has(system: System, sha: str) -> bool:
    try:
        get_backend().run(system, "cat-file", "-e", f"{sha}^{{commit}}", work_tree=False)
        return True
    except GitError:
        return False


def system_tip(system: System) -> str | None:
    try:
        return get_backend().run(system, "rev-parse", "--verify", "-q", f"refs/heads/{LOCAL_BRANCH}",
                                 work_tree=False) or None
    except GitError:
        return None


def is_ancestor(system: System, ancestor: str, descendant: str) -> bool:
    try:
        get_backend().run(system, "merge-base", "--is-ancestor", ancestor, descendant, work_tree=False)
        return True
    except GitError:
        return False


def _relay_import(slug: str, data: bytes, refspec: str) -> None:
    fd, path = tempfile.mkstemp(prefix="aidb-relay-", suffix=".bundle")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        relay_git(slug, "fetch", "-q", path, refspec, options=BUNDLE_FETCH_OPTIONS)
    finally:
        os.unlink(path)


def fetch_remote(system: System, secrets: RemoteSecrets) -> str | None:
    """Traz a branch de trabalho do remoto para a retransmissão e, dali, para o repositório do
    sistema em `refs/aidb/remote/<branch>` (sem tocar na branch local nem no workspace).
    Devolve o commit remoto, ou None se a branch não existe no remoto."""
    slug, branch = system.slug, secrets.working_branch
    ensure_relay(slug)
    url = secrets.address.ssh_url()
    listed = relay_git(slug, "ls-remote", url, f"refs/heads/{branch}", secrets=secrets).split()
    if not listed:
        return None
    remote_tip = listed[0]
    tracking = f"refs/remotes/origin/{branch}"
    relay_git(slug, "fetch", "-q", url, f"+refs/heads/{branch}:{tracking}", secrets=secrets)
    if not _system_has(system, remote_tip):
        revs = [tracking]
        local = system_tip(system)
        if local and _relay_has(slug, local):
            revs.append(f"^{local}")
        data = relay_git(slug, "bundle", "create", "-", *revs, raw=True)
        get_backend().import_bundle(system, data, f"+{tracking}:{remote_ref(branch)}")
    else:
        get_backend().run(system, "update-ref", remote_ref(branch), remote_tip, work_tree=False)
    return remote_tip


def _relay_has(slug: str, sha: str) -> bool:
    try:
        relay_git(slug, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except GitError:
        return False


def _send_to_relay(system: System, local: str, remote_tip: str | None) -> None:
    slug = system.slug
    if _relay_has(slug, local):
        relay_git(slug, "update-ref", _RELAY_LOCAL, local)
        return
    revs = [LOCAL_BRANCH]
    if remote_tip and _system_has(system, remote_tip):
        revs.append(f"^{remote_tip}")
    data = get_backend().export_bundle(system, revs)
    _relay_import(slug, data, f"+refs/heads/{LOCAL_BRANCH}:{_RELAY_LOCAL}")


def push(system: System, secrets: RemoteSecrets) -> str | None:
    """Envia os checkpoints locais à branch de trabalho, sem nunca reescrever o que já está lá.
    Devolve o commit enviado (None se não havia nada). Levanta `NeedsSync` se o remoto tem
    commits que o sistema ainda não integrou."""
    local = system_tip(system)
    if local is None:
        return None
    remote_tip = fetch_remote(system, secrets)
    if remote_tip == local:
        return None
    if remote_tip is not None and not is_ancestor(system, remote_tip, local):
        raise NeedsSync()
    _send_to_relay(system, local, remote_tip)
    relay_git(system.slug, "push", "-q", secrets.address.ssh_url(),
              f"{_RELAY_LOCAL}:refs/heads/{secrets.working_branch}", secrets=secrets)
    return local


def check_link(system: System, secrets: RemoteSecrets) -> str | None:
    """Vínculo inicial: recusa se a branch de trabalho do remoto já existe com histórico sem
    relação com o do sistema. Devolve o commit remoto (None se a branch não existe)."""
    remote_tip = fetch_remote(system, secrets)
    local = system_tip(system)
    if remote_tip is None or local is None:
        return remote_tip
    try:
        get_backend().run(system, "merge-base", local, remote_tip, work_tree=False)
    except GitError:
        raise UnrelatedHistory(secrets.working_branch) from None
    return remote_tip


# ---------------------------------------------------------------------------------------------
# Orquestração com estado e auditoria
# ---------------------------------------------------------------------------------------------


def _update_remote(system_id: str, **fields) -> None:
    from .db import session_scope
    from .models import SystemGitRemote

    with session_scope() as s:
        remote = s.get(SystemGitRemote, system_id)
        if remote is not None:
            for key, value in fields.items():
                setattr(remote, key, value)


def _remote_row(system_id: str):
    from .db import session_scope
    from .models import SystemGitRemote

    with session_scope() as s:
        remote = s.get(SystemGitRemote, system_id)
        if remote is not None:
            s.expunge(remote)
        return remote


def _audit(system: System, user: User | None, action: str, details: dict) -> None:
    from .services import audit

    audit.record(actor_id=user.id if user else None, actor_email=user.email if user else None,
                 action=action, resource_type="git_remote", resource_id=system.id,
                 system_id=system.id, details=details)


def activate(system: System, user: User) -> dict:
    """Ativa o vínculo: verifica o histórico da branch de trabalho remota, ativa e faz o primeiro
    envio (que cria a branch quando ela não existe)."""
    from .services import git_remote

    if not git_remote.can_manage_system(user, system):
        raise git_remote.NotPermitted("somente o dono do sistema ou um admin gerenciam o repositório remoto")
    secrets = git_remote.load_secrets(system.id)
    if secrets is None:
        raise git_remote.InvalidRemote("configure o endereço do repositório antes de ativar")
    if not secrets.host_key:
        raise git_remote.InvalidRemote("teste a conexão e confirme a identidade do servidor antes de ativar")
    from . import checkpoints

    checkpoints.ensure_repo(system)
    with system_lock(system.id):
        check_link(system, secrets)
    git_remote.set_enabled(system, user, True)
    push_now(system, user)
    return git_remote.get_view(system)


def push_now(system: System, user: User | None = None) -> dict | None:
    """Envia o que houver para enviar. Nunca levanta erro de remoto: grava o estado (`synced` ou
    `pending` com o motivo) para a aba Repositório. Não faz nada com o vínculo desativado ou com
    o sistema divergente (envios suspensos)."""
    from .services import git_remote

    remote = _remote_row(system.id)
    if remote is None or not remote.enabled or remote.state == "diverged":
        return None
    secrets = git_remote.load_secrets(system.id)
    from datetime import datetime, timezone

    with system_lock(system.id):
        try:
            sent = push(system, secrets)
        except RemoteError as exc:
            _update_remote(system.id, state="pending" if exc.kind != "host_key_changed" else "error",
                           state_detail=str(exc))
            _audit(system, user, "git_remote.push_failed", {"motivo": exc.kind})
            return {"sent": None, "error": str(exc), "kind": exc.kind}
        except GitError as exc:
            _update_remote(system.id, state="pending", state_detail=str(exc))
            return {"sent": None, "error": str(exc), "kind": "error"}
    fields = {"state": "synced", "state_detail": "", "last_synced_at": datetime.now(timezone.utc)}
    if sent:
        fields["last_pushed_sha"] = sent
        _audit(system, user, "git_remote.push", {"commit": sent[:12], "branch": secrets.working_branch})
    _update_remote(system.id, **fields)
    return {"sent": sent, "error": None, "kind": None}


def after_checkpoint(system: System, user: User | None = None) -> None:
    """Gancho chamado depois de todo checkpoint (execução, manual, restauração): envia ao remoto
    quando o vínculo está ativo. Nunca levanta erro — falha de remoto vira estado `pending`."""
    import logging

    try:
        push_now(system, user)
    except Exception:
        logging.getLogger(__name__).exception("envio ao remoto falhou para %s", system.slug)
