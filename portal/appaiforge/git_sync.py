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
    # a posição conhecida da branch remota passa a ser o que acabou de ser enviado
    get_backend().run(system, "update-ref", remote_ref(secrets.working_branch), local, work_tree=False)
    relay_git(system.slug, "update-ref", f"refs/remotes/origin/{secrets.working_branch}", local)
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
        try:
            sync(system, user)
        except (UnsavedChanges, Diverged, RemoteError, GitError):
            pass  # estado já gravado; o envio abaixo respeita divergência e pendência
        push_now(system, user)
    except Exception:
        logging.getLogger(__name__).exception("envio ao remoto falhou para %s", system.slug)


# ---------------------------------------------------------------------------------------------
# Sincronização (design D3, D4) e divergência (design D5)
# ---------------------------------------------------------------------------------------------

_CONFLICT_MARKERS = r"^(<<<<<<<|>>>>>>>)( |$)|^=======$"
PIPELINE_FILE = ".gitlab-ci.yml"


class UnsavedChanges(RemoteError):
    def __init__(self):
        super().__init__(
            "há alterações no workspace sem checkpoint e o repositório remoto tem alterações novas; "
            "salve ou descarte as alterações na aba Repositório antes de continuar",
            "unsaved",
        )


class Diverged(RemoteError):
    def __init__(self, files: list[str]):
        super().__init__("o remoto e o sistema alteraram os mesmos trechos: " + ", ".join(files), "diverged")
        self.files = files


def _git(system: System, *args: str) -> str:
    return get_backend().run(system, *args)


def merge_in_progress(system: System) -> bool:
    try:
        get_backend().run(system, "rev-parse", "-q", "--verify", "MERGE_HEAD", work_tree=False)
        return True
    except GitError:
        return False


def files_with_conflict_markers(system: System) -> list[str]:
    remote = _remote_row(system.id)
    candidates = list(remote.conflict_files or []) if remote is not None else []
    if not candidates:
        return []
    try:
        out = _git(system, "grep", "--no-index", "-l", "-E", _CONFLICT_MARKERS, "--", *candidates)
    except GitError as exc:
        if exc.returncode == 1:
            return []
        raise
    return [line for line in out.splitlines() if line]


def merge_concluded(system: System) -> None:
    """Chamado depois do commit que conclui uma resolução: o sistema deixa de estar divergente
    e o resultado pode ser enviado."""
    _update_remote(system.id, state="synced", state_detail="", conflict_files=None, merge_in_progress=False)


def protect_pipeline_file(system: System) -> None:
    """Design D8: com o vínculo ativo, alterações do workspace em `.gitlab-ci.yml` na raiz nunca
    vão para o remoto. Arquivo novo: fica fora do repositório (`info/exclude`, no GIT_DIR). Arquivo
    já rastreado e alterado ou apagado: volta à versão do último commit. Os dois casos geram aviso."""
    remote = _remote_row(system.id)
    if remote is None or not remote.enabled:
        return
    backend = get_backend()
    try:
        backend.run(system, "cat-file", "-e", f"HEAD:{PIPELINE_FILE}", work_tree=False)
        tracked = True
    except GitError:
        tracked = False
    if tracked:
        try:
            _git(system, "diff", "--quiet", "HEAD", "--", PIPELINE_FILE)
            return
        except GitError as exc:
            if exc.returncode != 1:
                raise
        _git(system, "checkout", "HEAD", "--", PIPELINE_FILE)
        _pipeline_warning(system, "alteração do agente em .gitlab-ci.yml desfeita: a definição do pipeline vem do repositório")
        return
    # só arquivo não rastreado e ainda não excluído: depois de excluído, nada a avisar de novo
    if _git(system, "ls-files", "--others", "--exclude-standard", "--", PIPELINE_FILE):
        backend.add_exclude(system, f"/{PIPELINE_FILE}")
        _pipeline_warning(system, ".gitlab-ci.yml criado no workspace foi deixado de fora do repositório")


def _pipeline_warning(system: System, message: str) -> None:
    _update_remote(system.id, state_detail=message)
    _audit(system, None, "git_remote.pipeline_file_ignored", {"aviso": message})


def _is_dirty(system: System) -> bool:
    return bool(_git(system, "status", "--porcelain"))


def _has_unsent(system: System, branch: str) -> bool:
    local = system_tip(system)
    try:
        remote = get_backend().run(system, "rev-parse", "-q", "--verify", remote_ref(branch), work_tree=False)
    except GitError:
        return local is not None
    return local is not None and not is_ancestor(system, local, remote)


def _integrate(system: System, branch: str, remote_tip: str, user: User | None) -> dict:
    """Integra `remote_tip` na branch local (design D3). Chamar com o lock do sistema."""
    from . import checkpoints

    local = system_tip(system)
    if local is not None and is_ancestor(system, remote_tip, local):
        return {"integrated": False}
    if _is_dirty(system):
        _update_remote(system.id, unsaved_blocked=True,
                       state_detail="alterações sem checkpoint aguardando decisão")
        raise UnsavedChanges()
    get_backend().prepare_work_tree(system)
    ref = remote_ref(branch)
    if local is None or is_ancestor(system, local, remote_tip):
        _git(system, "merge", "-q", "--ff-only", ref)
        message = f"sincroniza {branch} do repositório remoto"
    else:
        try:
            _git(system, "-c", "user.name=AIDB", "-c", "user.email=appaiforge@portal",
                 "merge", "-q", "--no-ff", "--no-edit", "-m", f"integra {branch} do repositório remoto", ref)
        except GitError:
            conflicted = [f for f in _git(system, "diff", "--name-only", "--diff-filter=U").splitlines() if f]
            _git(system, "merge", "--abort")
            _update_remote(system.id, state="diverged", conflict_files=conflicted, merge_in_progress=False,
                           state_detail="conflito com alterações do repositório remoto")
            raise Diverged(conflicted) from None
        message = f"integra {branch} do repositório remoto"
    head = system_tip(system)
    checkpoints.register_commit(system, head, message, checkpoints.ORIGIN_REMOTE, user)
    return {"integrated": True, "sha": head}


def sync(system: System, user: User | None = None) -> dict:
    """Traz para o workspace o que entrou na branch de trabalho remota. Divergente: só busca,
    não integra sozinho. Levanta `UnsavedChanges`, `Diverged` ou `RemoteError`."""
    from datetime import datetime, timezone

    from .services import git_remote

    remote = _remote_row(system.id)
    if remote is None or not remote.enabled:
        return {"integrated": False}
    secrets = git_remote.load_secrets(system.id)
    with system_lock(system.id):
        remote_tip = fetch_remote(system, secrets)
        if remote_tip is None or remote.state == "diverged":
            return {"integrated": False}
        result = _integrate(system, secrets.working_branch, remote_tip, user)
    _update_remote(system.id, unsaved_blocked=False, last_synced_at=datetime.now(timezone.utc),
                   **({"state_detail": ""} if remote.state != "pending" else {}))
    if result.get("integrated"):
        _audit(system, user, "git_remote.sync", {"commit": result["sha"][:12]})
    return result


def before_run(system: System, user: User | None = None) -> str | None:
    """Antes de acionar o agente (design D6): sincroniza. Devolve a mensagem que impede a execução
    (alterações não salvas) ou None. Remoto fora do ar ou divergente não impedem a execução."""
    try:
        sync(system, user)
    except UnsavedChanges as exc:
        return str(exc)
    except Diverged:
        _audit(system, user, "git_remote.diverged", {})
        return None
    except (RemoteError, GitError) as exc:
        _update_remote(system.id, state_detail=f"sincronização antes da execução falhou: {exc}")
        return None
    return None


def save_unsaved(system: System, user: User) -> dict:
    """Ação "Salvar como checkpoint": registra as alterações não salvas e sincroniza."""
    from . import checkpoints

    checkpoints.record_checkpoint(system, None, "alterações não salvas antes de sincronizar", user,
                                  origin=checkpoints.ORIGIN_MANUAL)
    _audit(system, user, "git_remote.unsaved_saved", {})
    result = sync(system, user)
    push_now(system, user)
    return result


def discard_unsaved(system: System, user: User) -> dict:
    """Ação "Descartar alterações não salvas": volta ao último checkpoint e sincroniza."""
    with system_lock(system.id):
        get_backend().prepare_work_tree(system)
        if system_tip(system) is not None:
            _git(system, "reset", "-q", "--hard", "HEAD")
        _git(system, "clean", "-fdq")
    _audit(system, user, "git_remote.unsaved_discarded", {})
    result = sync(system, user)
    push_now(system, user)
    return result


def resolve_in_workspace(system: System, user: User) -> list[str]:
    """Leva o conflito para os arquivos do workspace (marcas de conflito) para o agente ou o
    editor resolverem; o merge conclui no checkpoint seguinte sem marcas (design D5)."""
    from .services import git_remote

    remote = _remote_row(system.id)
    if remote is None or remote.state != "diverged":
        raise git_remote.InvalidRemote("o sistema não está divergente")
    branch = remote.working_branch
    with system_lock(system.id):
        if merge_in_progress(system):
            return list(remote.conflict_files or [])
        get_backend().prepare_work_tree(system)
        try:
            _git(system, "-c", "user.name=AIDB", "-c", "user.email=appaiforge@portal",
                 "merge", "-q", "--no-ff", "--no-commit", remote_ref(branch))
        except GitError:
            pass  # conflito esperado: as marcas ficam nos arquivos
        conflicted = [f for f in _git(system, "diff", "--name-only", "--diff-filter=U").splitlines() if f]
    _update_remote(system.id, merge_in_progress=True, conflict_files=conflicted or list(remote.conflict_files or []),
                   state_detail="resolução em andamento no workspace")
    _audit(system, user, "git_remote.resolution_started", {"arquivos": conflicted})
    return conflicted


def cancel_resolution(system: System, user: User) -> None:
    with system_lock(system.id):
        if merge_in_progress(system):
            _git(system, "merge", "--abort")
    _update_remote(system.id, merge_in_progress=False, state_detail="conflito com alterações do repositório remoto")
    _audit(system, user, "git_remote.resolution_cancelled", {})


def unsent_checkpoints(system: System) -> list[dict]:
    """Checkpoints locais que não estão na branch remota (o que "adotar o remoto" deixa de lado)."""
    from . import checkpoints

    remote = _remote_row(system.id)
    if remote is None:
        return []
    try:
        shas = set(_git(system, "rev-list", f"{remote_ref(remote.working_branch)}..refs/heads/{LOCAL_BRANCH}").split())
    except GitError:
        return []
    return [cp for cp in checkpoints.list_checkpoints(system) if cp["git_sha"] in shas]


def adopt_remote(system: System, user: User) -> str:
    """Ação "Adotar a versão do remoto" (design D5): o workspace passa a ter o conteúdo da branch
    remota; os checkpoints locais deixados de lado continuam restauráveis (referência de
    proteção); nada é enviado ao remoto."""
    from . import checkpoints
    from .services import git_remote

    remote = _remote_row(system.id)
    if remote is None or remote.state != "diverged":
        raise git_remote.InvalidRemote("o sistema não está divergente")
    ref = remote_ref(remote.working_branch)
    with system_lock(system.id):
        if merge_in_progress(system):
            _git(system, "merge", "--abort")
        local = system_tip(system)
        if local:
            get_backend().run(system, "update-ref", f"refs/aidb/set-aside/{local}", local, work_tree=False)
        get_backend().prepare_work_tree(system)
        _git(system, "reset", "-q", "--hard", ref)
        _git(system, "clean", "-fdq")
        head = system_tip(system)
        checkpoints.register_commit(system, head, "adota a versão do repositório remoto", checkpoints.ORIGIN_REMOTE, user)
    _update_remote(system.id, state="synced", state_detail="", conflict_files=None, merge_in_progress=False,
                   last_pushed_sha=head)
    _audit(system, user, "git_remote.adopt_remote", {"commit": head[:12], "deixado_de_lado": (local or "")[:12]})
    return head


class RunInProgress(RemoteError):
    def __init__(self):
        super().__init__("há uma execução do agente em andamento; tente de novo quando ela terminar", "busy")


def _run_in_progress(system_id: str) -> bool:
    from sqlalchemy import select

    from .db import session_scope
    from .models import AgentRun, RunStatus

    with session_scope() as s:
        return s.execute(
            select(AgentRun.id).where(
                AgentRun.system_id == system_id,
                AgentRun.status.in_([RunStatus.running, RunStatus.awaiting_approval]),
            )
        ).first() is not None


def sync_now(system: System, user: User) -> dict:
    """Ação "Sincronizar agora": recusada com execução em andamento (o workspace não muda durante
    uma execução); com alterações não salvas, levanta `UnsavedChanges` como antes de uma execução."""
    if _run_in_progress(system.id):
        raise RunInProgress()
    result = sync(system, user)
    push_now(system, user)
    return result


# ---------------------------------------------------------------------------------------------
# Promoção pela API do GitLab (design D7)
# ---------------------------------------------------------------------------------------------

DEVELOPER_ACCESS = 30


def _gitlab(secrets: RemoteSecrets, method: str, path: str, **kwargs):
    import httpx

    url = f"{secrets.api_url.rstrip('/')}/api/v4{path}"
    try:
        with httpx.Client(timeout=REMOTE_TIMEOUT, follow_redirects=False) as client:
            response = client.request(method, url, headers={"PRIVATE-TOKEN": secrets.api_token}, **kwargs)
    except httpx.TransportError as exc:
        # erros do httpx não são OSError: sem isto, "Testar token" com o endereço errado falhava
        # sem nenhuma mensagem na tela. O endereço vai na mensagem para o editor conferir.
        raise RemoteError(f"API do GitLab inacessível em {secrets.api_url}: {exc}", "unreachable") from None
    if response.status_code in (401, 403):
        raise RemoteError("o GitLab recusou o token de API do sistema", "access_denied")
    if response.status_code == 404:
        raise RemoteError("o token de API não alcança o projeto do repositório", "access_denied")
    if response.status_code >= 400:
        raise RemoteError(f"erro da API do GitLab: {response.status_code} {response.text[:200]}")
    return response.json()


def _project_path(secrets: RemoteSecrets) -> str:
    from .services.git_remote import project_api_path

    return f"/projects/{project_api_path(secrets.address)}"


def check_api_token(system: System) -> str:
    """Teste do token: o projeto é alcançável e o acesso permite abrir merge request. Não escreve
    nada no GitLab. Devolve uma mensagem para o editor; levanta `RemoteError` em falha."""
    from .services import git_remote

    secrets = git_remote.load_secrets(system.id)
    if secrets is None or not secrets.api_token:
        raise RemoteError("cadastre um token de API antes de testar", "access_denied")
    try:
        project = _gitlab(secrets, "GET", _project_path(secrets))
    except OSError as exc:
        raise RemoteError(f"API do GitLab inacessível: {exc}", "unreachable") from None
    permissions = project.get("permissions") or {}
    levels = [(permissions.get(k) or {}).get("access_level") or 0 for k in ("project_access", "group_access")]
    if max(levels) < DEVELOPER_ACCESS:
        raise RemoteError("o token alcança o projeto, mas sem permissão para abrir merge request "
                          "(é preciso papel Developer ou maior)", "access_denied")
    return f"Token válido para {project.get('path_with_namespace', secrets.address.path)}."


def request_promotion(system: System, user: User) -> dict:
    """Ação "Solicitar promoção": mostra o MR aberto entre as branches ou abre um. Sem token, ou
    com o token recusado, devolve o endereço de criação preenchido sem abrir nada."""
    from .services import git_remote

    if not git_remote.can_manage_system(user, system):
        raise git_remote.NotPermitted("somente o dono do sistema ou um admin gerenciam o repositório remoto")
    remote = _remote_row(system.id)
    if remote is None or not remote.enabled:
        raise git_remote.InvalidRemote("ative o vínculo com o repositório antes de solicitar promoção")
    if remote.state == "diverged":
        raise git_remote.InvalidRemote("resolva a divergência com o repositório remoto antes de solicitar promoção")
    if remote.state == "pending" or _has_unsent(system, remote.working_branch):
        raise git_remote.InvalidRemote("há checkpoints ainda não enviados; use \"Enviar agora\" antes de solicitar promoção")
    secrets = git_remote.load_secrets(system.id)
    fallback = git_remote.create_mr_url(remote)
    if not secrets.api_token:
        _audit(system, user, "git_remote.promotion_link", {})
        return {"url": fallback, "created": False, "existing": False, "fallback": True,
                "message": "Sem token de API: abra o merge request pelo link."}
    base = _project_path(secrets)
    params = {"state": "opened", "source_branch": secrets.working_branch, "target_branch": secrets.target_branch}
    try:
        found = _gitlab(secrets, "GET", f"{base}/merge_requests", params=params)
        if found:
            url, created = found[0]["web_url"], False
        else:
            mr = _gitlab(secrets, "POST", f"{base}/merge_requests", json={
                "source_branch": secrets.working_branch, "target_branch": secrets.target_branch,
                "title": f"Promove {secrets.working_branch} para {secrets.target_branch} — {system.name}",
                "description": _promotion_description(system),
                "remove_source_branch": False,
            })
            url, created = mr["web_url"], True
    except RemoteError as exc:
        if exc.kind != "access_denied":
            raise
        _audit(system, user, "git_remote.promotion_link", {"motivo": "token recusado"})
        return {"url": fallback, "created": False, "existing": False, "fallback": True,
                "message": f"{exc}: abra o merge request pelo link."}
    except OSError as exc:
        raise RemoteError(f"API do GitLab inacessível: {exc}", "unreachable") from None
    _update_remote(system.id, last_mr_url=url)
    _audit(system, user, "git_remote.promotion", {"merge_request": url, "aberto_agora": created})
    return {"url": url, "created": created, "existing": not created, "fallback": False,
            "message": "Merge request aberto." if created else "Já existe um merge request aberto."}


def _promotion_description(system: System) -> str:
    from . import checkpoints

    lines = [f"Solicitado pelo AIDB a partir do sistema **{system.name}** (`{system.slug}`).", "",
             "Últimos checkpoints:"]
    for cp in checkpoints.list_checkpoints(system)[:10]:
        lines.append(f"- `{cp['git_sha'][:8]}` {cp['message'][:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Manifesto de conexões (change add-deploy-only-system, D8)
# ---------------------------------------------------------------------------------------------

MANIFEST_FILE = ".aidb/manifest.json"


def connections_manifest(system_id: str) -> str:
    """Conteúdo do manifesto: alias e tipo de cada conexão ativa no sistema, nenhuma credencial.

    O alias ocupa o campo `name` (change add-db-manager-role): é o nome que o código usa
    (`DATABASE_URL_<ALIAS>`); conexões autorizadas e não ativadas ficam de fora."""
    import json

    from .services.connections import active_connections

    rows = sorted((c.alias, c.kind) for c in active_connections(system_id))
    data = {"version": 1, "connections": [{"name": name, "kind": kind} for name, kind in rows]}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_connections_manifest(system: System) -> None:
    """Com o vínculo ativo, reescreve o manifesto no workspace antes do commit do checkpoint — o
    que o agente tiver escrito nele é sobrescrito. Sem vínculo ativo, nada é gravado."""
    remote = _remote_row(system.id)
    if remote is None or not remote.enabled:
        return
    content = connections_manifest(system.id).encode()
    if get_settings().provisioning_driver == "kubernetes":
        from .drivers.kubernetes_driver import write_workspace_files

        write_workspace_files(system, {MANIFEST_FILE: content})
        return
    path = os.path.join(get_settings().workspaces_dir, system.slug, MANIFEST_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
