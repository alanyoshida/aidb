"""Vínculo de um sistema com um repositório git remoto (change add-system-git-remote, capability
system-git-remote): configuração, chave de implantação e token de API.

Este módulo só guarda e valida a configuração; o envio, a sincronização e a promoção ficam em
`git_sync`. Segredos (chave privada e token) são cifrados com `security.encrypt_secret`, nunca
são devolvidos por nenhuma função pública daqui e nunca entram na auditoria.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..db import session_scope
from ..models import System, SystemGitRemote, User
from ..rbac import can_manage_system
from ..security import decrypt_secret, encrypt_secret
from . import audit

DEFAULT_WORKING_BRANCH = "homolog"
DEFAULT_TARGET_BRANCH = "main"


class NotPermitted(Exception):
    pass


class InvalidRemote(ValueError):
    """Endereço, branch ou endereço de API recusado; a mensagem é exibível ao editor."""


@dataclass(frozen=True)
class RemoteAddress:
    user: str
    host: str
    port: int | None
    path: str  # caminho do projeto, sem barra inicial e sem `.git` (ex.: "time/app")

    def ssh_url(self) -> str:
        port = f":{self.port}" if self.port else ""
        return f"ssh://{self.user}@{self.host}{port}/{self.path}.git"


# Host: nome DNS, IPv4 ou IPv6 entre colchetes. Nunca começa com "-" (seria lido como opção do ssh).
_HOST = r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])"
_USER = r"[A-Za-z0-9._-]+"
_PATH = r"[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*"
_SSH_URL = re.compile(rf"^ssh://(?:(?P<user>{_USER})@)?(?P<host>{_HOST})(?::(?P<port>\d{{1,5}}))?/(?P<path>{_PATH})$")
_SCP_URL = re.compile(rf"^(?P<user>{_USER})@(?P<host>{_HOST}):(?P<path>{_PATH})$")
_FORMAT_HELP = "use ssh://usuario@host[:porta]/grupo/projeto.git ou usuario@host:grupo/projeto.git"


def parse_remote_url(url: str) -> RemoteAddress:
    """Valida o endereço do repositório. Só git por SSH: `ext::`, `file://`, HTTP e caminhos
    locais são recusados, e nenhuma parte pode começar com "-"."""
    url = (url or "").strip()
    match = _SSH_URL.match(url) or _SCP_URL.match(url)
    if match is None:
        raise InvalidRemote(f"endereço do repositório inválido: {_FORMAT_HELP}")
    user = match.group("user") or "git"
    host = match.group("host")
    path = match.group("path")
    if user.startswith("-") or host.startswith("-") or path.startswith("-"):
        raise InvalidRemote(f"endereço do repositório inválido: {_FORMAT_HELP}")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not path or ".." in path.split("/"):
        raise InvalidRemote(f"endereço do repositório inválido: {_FORMAT_HELP}")
    port = int(match.group("port")) if "port" in match.groupdict() and match.group("port") else None
    if port is not None and not 0 < port < 65536:
        raise InvalidRemote("porta SSH inválida")
    return RemoteAddress(user=user, host=host, port=port, path=path)


_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_branch(name: str, label: str) -> str:
    """Nome de branch conservador: letras, dígitos, ".", "_", "-" e "/"; sem começar com "-" ou
    "/", sem "..", sem "//" e sem terminar em "/", "." ou ".lock" (regras do git)."""
    name = (name or "").strip()
    if (
        not name
        or len(name) > 200
        or not _BRANCH.match(name)
        or name.startswith(("-", "/", "."))
        or name.endswith(("/", ".", ".lock"))
        or ".." in name
        or "//" in name
        or "/." in name
    ):
        raise InvalidRemote(f"nome de branch inválido para {label}: {name!r}")
    return name


def derive_api_url(address: RemoteAddress) -> str:
    return f"https://{address.host}"


def validate_api_url(api_url: str) -> str:
    api_url = (api_url or "").strip().rstrip("/")
    if not api_url:
        return ""
    if not re.match(rf"^https?://{_HOST}(?::\d{{1,5}})?(?:/[A-Za-z0-9._~/-]*)?$", api_url):
        raise InvalidRemote("endereço da API inválido: use https://host[:porta]")
    return api_url


def effective_api_url(remote: SystemGitRemote) -> str:
    return remote.api_url or derive_api_url(parse_remote_url(remote.url))


def project_api_path(address: RemoteAddress) -> str:
    """Identificador do projeto na API do GitLab: o caminho codificado ("time%2Fapp")."""
    return quote(address.path, safe="")


def create_mr_url(remote: SystemGitRemote) -> str:
    """Endereço de criação de merge request já preenchido com as duas branches."""
    base = effective_api_url(remote)
    path = parse_remote_url(remote.url).path
    return (
        f"{base}/{path}/-/merge_requests/new"
        f"?merge_request%5Bsource_branch%5D={quote(remote.working_branch, safe='')}"
        f"&merge_request%5Btarget_branch%5D={quote(remote.target_branch, safe='')}"
    )


# ---------------------------------------------------------------------------------------------
# Chave de implantação
# ---------------------------------------------------------------------------------------------


def _generate_keypair(slug: str) -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
    ).decode()
    public = private.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode()
    return private_pem, f"{public} aidb-{slug}"


def fingerprint(public_key: str) -> str:
    """Impressão digital SHA256 no formato do `ssh-keygen -l`."""
    blob = base64.b64decode(public_key.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def _require_manager(user: User, system: System) -> None:
    if not can_manage_system(user, system):
        raise NotPermitted("somente o dono do sistema ou um admin gerenciam o repositório remoto")


def _audit(user: User | None, system: System, action: str, details: dict) -> None:
    audit.record(
        actor_id=user.id if user else None, actor_email=user.email if user else None,
        action=action, resource_type="git_remote", resource_id=system.id,
        system_id=system.id, details=details,
    )


def ensure_remote(system: System, user: User) -> dict:
    """Devolve a configuração do sistema, gerando o par de chaves na primeira vez (o editor vê a
    chave pública ao abrir a aba, antes mesmo de informar o endereço)."""
    _require_manager(user, system)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        if remote is None:
            private_pem, public = _generate_keypair(system.slug)
            remote = SystemGitRemote(
                system_id=system.id, public_key=public, private_key_encrypted=encrypt_secret(private_pem),
                working_branch=DEFAULT_WORKING_BRANCH, target_branch=DEFAULT_TARGET_BRANCH,
            )
            s.add(remote)
            s.flush()
            created = True
        else:
            created = False
        view = _view(remote)
    if created:
        _audit(user, system, "git_remote.key_create", {"impressao_digital": fingerprint(view["public_key"])})
    return view


def _view(remote: SystemGitRemote) -> dict:
    """O que pode sair deste módulo: nunca a chave privada nem o token."""
    return {
        "url": remote.url,
        "working_branch": remote.working_branch,
        "target_branch": remote.target_branch,
        "public_key": remote.public_key,
        "fingerprint": fingerprint(remote.public_key),
        "host_key_confirmed": bool(remote.host_key),
        "api_url": remote.api_url,
        "effective_api_url": effective_api_url(remote) if remote.url else "",
        "has_api_token": bool(remote.api_token_encrypted),
        "enabled": remote.enabled,
        "state": remote.state,
        "state_detail": remote.state_detail,
        "last_pushed_sha": remote.last_pushed_sha,
        "last_synced_at": remote.last_synced_at.isoformat() if remote.last_synced_at else None,
        "conflict_files": list(remote.conflict_files or []),
        "merge_in_progress": remote.merge_in_progress,
        "unsaved_blocked": remote.unsaved_blocked,
        "last_mr_url": remote.last_mr_url,
    }


def get_view(system: System) -> dict | None:
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        return _view(remote) if remote is not None else None


def configure(
    system: System, user: User, *, url: str, working_branch: str = "", target_branch: str = "",
    api_url: str = "",
) -> dict:
    """Grava endereço, branches e endereço da API. Mudar o endereço desfaz a confirmação da
    identidade do servidor e desativa o vínculo até um novo teste de conexão."""
    _require_manager(user, system)
    address = parse_remote_url(url)
    working = validate_branch(working_branch or DEFAULT_WORKING_BRANCH, "branch de trabalho")
    target = validate_branch(target_branch or DEFAULT_TARGET_BRANCH, "branch de destino")
    if working == target:
        raise InvalidRemote("a branch de trabalho e a de destino precisam ser diferentes")
    api = validate_api_url(api_url)
    ensure_remote(system, user)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        if remote.url != address.ssh_url():
            remote.host_key = None
            remote.enabled = False
        remote.url = address.ssh_url()
        remote.working_branch = working
        remote.target_branch = target
        remote.api_url = api
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.configure",
           {"url": view["url"], "branch_trabalho": working, "branch_destino": target, "api": api or "(derivada)"})
    return view


def rotate_key(system: System, user: User) -> dict:
    """Gera um par novo; o anterior deixa de ser usado imediatamente."""
    _require_manager(user, system)
    ensure_remote(system, user)
    private_pem, public = _generate_keypair(system.slug)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        remote.public_key = public
        remote.private_key_encrypted = encrypt_secret(private_pem)
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.key_rotate", {"impressao_digital": view["fingerprint"]})
    return view


def set_api_token(system: System, user: User, token: str) -> dict:
    _require_manager(user, system)
    token = (token or "").strip()
    if not token or any(ch.isspace() for ch in token):
        raise InvalidRemote("token de API vazio ou com espaços")
    ensure_remote(system, user)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        remote.api_token_encrypted = encrypt_secret(token)
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.api_access_set", {})
    return view


def remove_api_token(system: System, user: User) -> dict:
    _require_manager(user, system)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        if remote is None:
            raise InvalidRemote("o sistema não tem repositório remoto configurado")
        remote.api_token_encrypted = None
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.api_access_remove", {})
    return view


def confirm_host_key(system: System, user: User, host_key: str) -> dict:
    """Grava a chave do servidor que o editor confirmou ter visto (linhas "tipo base64")."""
    _require_manager(user, system)
    lines = [line.strip() for line in (host_key or "").splitlines() if line.strip()]
    if not lines or any(len(line.split()) != 2 for line in lines):
        raise InvalidRemote("chave do servidor em formato inesperado")
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        if remote is None or not remote.url:
            raise InvalidRemote("configure o endereço do repositório antes de confirmar o servidor")
        remote.host_key = "\n".join(lines)
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.host_confirm", {"servidor": [fingerprint(line) for line in lines]})
    return view


def set_enabled(system: System, user: User, enabled: bool) -> dict:
    """Ativa ou desativa o vínculo. Ativar exige endereço configurado e identidade do servidor
    confirmada; desativar não toca no workspace, no histórico nem no remoto."""
    _require_manager(user, system)
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system.id)
        if remote is None or not remote.url:
            raise InvalidRemote("configure o endereço do repositório antes de ativar")
        if enabled and not remote.host_key:
            raise InvalidRemote("teste a conexão e confirme a identidade do servidor antes de ativar")
        remote.enabled = enabled
        s.flush()
        view = _view(remote)
    _audit(user, system, "git_remote.enable" if enabled else "git_remote.disable", {})
    return view


def delete_for_system(system_id: str) -> None:
    """Exclusão definitiva: remove configuração, chave e token (nada no remoto muda)."""
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system_id)
        if remote is not None:
            s.delete(remote)


# ---------------------------------------------------------------------------------------------
# Segredos: só para uso interno do portal (git_sync), nunca para a interface nem para logs.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteSecrets:
    address: RemoteAddress
    private_key: str
    host_key: str | None
    api_url: str
    api_token: str | None
    working_branch: str
    target_branch: str

    def __repr__(self) -> str:  # nunca vaza segredo em log ou traceback
        return f"RemoteSecrets(address={self.address!r}, api_url={self.api_url!r})"


def load_secrets(system_id: str) -> RemoteSecrets | None:
    with session_scope() as s:
        remote = s.get(SystemGitRemote, system_id)
        if remote is None or not remote.url:
            return None
        return RemoteSecrets(
            address=parse_remote_url(remote.url),
            private_key=decrypt_secret(remote.private_key_encrypted),
            host_key=remote.host_key,
            api_url=effective_api_url(remote),
            api_token=decrypt_secret(remote.api_token_encrypted) if remote.api_token_encrypted else None,
            working_branch=remote.working_branch,
            target_branch=remote.target_branch,
        )
