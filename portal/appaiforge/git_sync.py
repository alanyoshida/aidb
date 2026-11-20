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
from .git_backend import SAFE_OPTIONS, GitError, git_env
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
              stdin: bytes | None = None, timeout: int = REMOTE_TIMEOUT) -> str:
    """git na cópia de retransmissão. Com `secrets`, pode falar com o remoto por SSH (e só SSH)."""
    path = relay_dir(slug)
    env = git_env(path, None)
    extra: tuple[str, ...] = ()
    with contextlib.ExitStack() as stack:
        if secrets is not None:
            env.update(stack.enter_context(ssh_env(secrets, host_key=host_key)))
            extra = ("-c", "protocol.ssh.allow=always")
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
    return result.stdout.decode(errors="replace")


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
