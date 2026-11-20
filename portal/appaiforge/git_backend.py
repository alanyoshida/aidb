"""Backend git por driver para o repositório de cada sistema (change
`isolate-workspace-repository`, capability `workspace-repository`, design D1-D4).

O workspace (`/workspace`) é só a ÁRVORE DE TRABALHO. O repositório — objetos, refs, config e
hooks — vive num lugar que o agente e a app gerada não alcançam:

- driver Docker: `<gitdirs_dir>/<slug>`, num volume montado só no portal;
- driver Kubernetes: num PVC próprio montado só no container auxiliar `git` do pod.

Toda invocação de git passa por aqui com `GIT_DIR`/`GIT_WORK_TREE` explícitos, ambiente
construído do zero (sem `HOME`, sem config global/de sistema) e um conjunto fixo de opções de
linha de comando. Com isso, nada que o agente escreva no workspace — hooks, `core.fsmonitor`,
filtros, `include.path`, um `.git` plantado — é lido ou executado pelo portal: o `.git` que
estiver no workspace é só um diretório que o git nunca rastreia, e `.gitattributes` só ativa um
filtro se a config o definir, o que a config escrita pelo portal nunca faz.

Ponto de entrada para o resto do portal: `get_backend()`.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from typing import Protocol

from .config import get_settings
from .models import ExecutionMode, System


class GitError(Exception):
    def __init__(self, message: str = "", returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


# Opções passadas em TODA chamada, além da config do repositório (que é escrita só pelo portal):
# defesa em profundidade caso a config do GIT_DIR algum dia divirja do que `init_config` grava.
# `safe.directory` vem pela linha de comando porque só é aceito em config "protegida" (sistema,
# global ou -c) — a global está desligada de propósito (GIT_CONFIG_GLOBAL=/dev/null).
SAFE_OPTIONS: tuple[str, ...] = (
    "-c", "safe.directory=*",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "core.untrackedCache=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "core.excludesFile=/dev/null",
    "-c", "protocol.allow=never",
)

# Config gravada no repositório na criação. Nenhuma entrada define filtro, driver, hook ou
# include — a ausência é o que torna `.gitattributes` do workspace inofensivo.
REPO_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.bare", "false"),
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.untrackedCache", "false"),
    ("commit.gpgsign", "false"),
    ("gc.autoDetach", "false"),
    ("user.name", "AIDB"),
    ("user.email", "appaiforge@portal"),
)

_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Buscar de um pacote local é transporte "file", proibido por `protocol.allow=never`; liberado só
# nesta operação, e com validação de todo objeto recebido.
BUNDLE_FETCH_OPTIONS: tuple[str, ...] = (
    "-c", "protocol.file.allow=always",
    "-c", "fetch.fsckObjects=true",
)


def git_env(git_dir: str, work_tree: str | None) -> dict[str, str]:
    """Ambiente completo de uma chamada git — construído do zero, nunca herdado do processo do
    portal (que pode ter `GIT_*`, `HOME` e `XDG_CONFIG_HOME` próprios)."""
    env = {
        "PATH": _SAFE_PATH,
        "LC_ALL": "C",
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_DIR": git_dir,
    }
    if work_tree is not None:
        env["GIT_WORK_TREE"] = work_tree
    return env


# Só arquivos de objeto entram na migração: diretórios `xx/` com nomes hexadecimais e os
# pacotes. `objects/info/alternates` fica de fora de propósito — apontaria o repositório novo
# para outros diretórios de objetos.
_LOOSE_DIR = re.compile(r"^[0-9a-f]{2}$")
_LOOSE_FILE = re.compile(r"^[0-9a-f]{38,62}$")
_PACK_FILE = re.compile(r"^pack-[0-9a-f]{40,64}\.(pack|idx|rev)$")


def run_identity(system: System) -> tuple[int, int]:
    """uid/gid com que o git roda (design D3): o mesmo dono do workspace — o usuário do agente
    nos modos `reduced`/`sandboxed`, root no `legacy`. Decidido pelo modo de execução gravado
    no sistema, nunca pelo dono atual do diretório (que o agente controla)."""
    from .drivers.docker_driver import AGENT_GID, AGENT_UID

    if system.execution_mode in (ExecutionMode.reduced, ExecutionMode.sandboxed):
        return AGENT_UID, AGENT_GID
    return 0, 0


class GitBackend(Protocol):
    def run(self, system: System, *args: str, work_tree: bool = True) -> str: ...

    def is_initialized(self, system: System) -> bool: ...

    def create(self, system: System) -> None: ...

    def import_legacy_objects(self, system: System) -> None: ...

    def prepare_work_tree(self, system: System) -> None: ...

    def export_bundle(self, system: System, revs: list[str]) -> bytes: ...

    def add_exclude(self, system: System, pattern: str) -> None: ...

    def import_bundle(self, system: System, data: bytes, refspec: str) -> None: ...

    def remove(self, system: System) -> None: ...


class DockerGitBackend:
    """Repositório em `<gitdirs_dir>/<slug>`, operado por subprocesso no próprio portal. Quando
    o portal roda como root (imagem do portal), o subprocesso troca para o uid/gid do dono do
    workspace; fora disso (testes locais) roda com a identidade do processo."""

    def git_dir(self, system: System) -> str:
        return os.path.join(get_settings().gitdirs_dir, system.slug)

    def work_tree(self, system: System) -> str:
        return os.path.join(get_settings().workspaces_dir, system.slug)

    def _identity_kwargs(self, system: System) -> dict:
        if os.geteuid() != 0:
            return {}
        uid, gid = run_identity(system)
        if uid == 0:
            return {}
        return {"user": uid, "group": gid, "extra_groups": []}

    def run(self, system: System, *args: str, work_tree: bool = True) -> str:
        git_dir = self.git_dir(system)
        tree = self.work_tree(system) if work_tree else None
        if tree is not None:
            os.makedirs(tree, exist_ok=True)
        result = subprocess.run(
            ["git", *SAFE_OPTIONS, *args],
            cwd=tree or git_dir,
            env=git_env(git_dir, tree),
            capture_output=True,
            text=True,
            timeout=60,
            **self._identity_kwargs(system),
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args[:2])}: {result.stderr.strip()}", result.returncode)
        return result.stdout.strip()

    def is_initialized(self, system: System) -> bool:
        return os.path.isfile(os.path.join(self.git_dir(system), "HEAD"))

    def _run_bytes(self, system: System, args: list[str], *, stdin: bytes | None = None,
                   extra: tuple[str, ...] = ()) -> bytes:
        git_dir = self.git_dir(system)
        result = subprocess.run(
            ["git", *SAFE_OPTIONS, *extra, *args], cwd=git_dir, env=git_env(git_dir, None),
            input=stdin, capture_output=True, timeout=120, **self._identity_kwargs(system),
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()}", result.returncode)
        return result.stdout

    def add_exclude(self, system: System, pattern: str) -> None:
        """Acrescenta um padrão ao `info/exclude` do repositório (no GIT_DIR, fora do workspace)."""
        path = os.path.join(self.git_dir(system), "info", "exclude")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = open(path).read().splitlines() if os.path.exists(path) else []
        if pattern not in existing:
            with open(path, "a") as f:
                f.write(pattern + "\n")
            self._chown(path, system)
            self._chown(os.path.dirname(path), system)

    def export_bundle(self, system: System, revs: list[str]) -> bytes:
        """Pacote git (`git bundle`) com `revs` (ex.: ["main", "^<sha já no remoto>"])."""
        return self._run_bytes(system, ["bundle", "create", "-", *revs])

    def import_bundle(self, system: System, data: bytes, refspec: str) -> None:
        """Busca um pacote no repositório do sistema, só para a referência de `refspec`, validando
        os objetos recebidos. O pacote vai para um arquivo temporário legível pelo uid do git."""
        import tempfile

        fd, path = tempfile.mkstemp(prefix="aidb-", suffix=".bundle")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(path, 0o644)
            self._run_bytes(system, ["fetch", "-q", path, refspec], extra=BUNDLE_FETCH_OPTIONS)
        finally:
            os.unlink(path)

    def _chown(self, path: str, system: System) -> None:
        if os.geteuid() != 0:
            return
        uid, gid = run_identity(system)
        os.chown(path, uid, gid, follow_symlinks=False)

    def create(self, system: System) -> None:
        git_dir = self.git_dir(system)
        os.makedirs(git_dir, exist_ok=True)
        os.chmod(git_dir, 0o700)
        self._chown(git_dir, system)

    def import_legacy_objects(self, system: System) -> None:
        """Copia, como DADO, os objetos do `.git` antigo do workspace para o repositório novo
        (design D4). Só arquivos regulares de objeto; links simbólicos e qualquer outro arquivo
        do `.git` antigo (config, hooks, refs, alternates) são ignorados."""
        src_objects = os.path.join(self.work_tree(system), ".git", "objects")
        if not _is_real_dir(os.path.join(self.work_tree(system), ".git")) or not _is_real_dir(src_objects):
            return
        dst_objects = os.path.join(self.git_dir(system), "objects")
        for entry in os.listdir(src_objects):
            src_dir = os.path.join(src_objects, entry)
            if not _is_real_dir(src_dir):
                continue
            if _LOOSE_DIR.match(entry):
                pattern = _LOOSE_FILE
            elif entry == "pack":
                pattern = _PACK_FILE
            else:
                continue
            dst_dir = os.path.join(dst_objects, entry)
            for name in os.listdir(src_dir):
                if not pattern.match(name):
                    continue
                src = os.path.join(src_dir, name)
                dst = os.path.join(dst_dir, name)
                if os.path.exists(dst):
                    continue
                if not os.path.isdir(dst_dir):
                    os.makedirs(dst_dir, exist_ok=True)
                    self._chown(dst_dir, system)
                if _copy_regular_file(src, dst):
                    self._chown(dst, system)

    def prepare_work_tree(self, system: System) -> None:
        """Antes de o git ESCREVER na árvore de trabalho (migração, restauração): passa ao dono
        do workspace o que estiver com o root lá dentro — deixado pelo portal antigo, que
        restaurava como root, ou pelo `materialize` das guidelines. Sem isto, o git (que roda com
        o uid do agente, design D3) não consegue reescrever esses caminhos.

        Só age com o portal rodando como root e o sistema fora do modo `legacy`. A varredura é
        por descritor de diretório e nunca segue link simbólico (`os.fwalk` + `chown` relativo ao
        descritor, sem seguir link): o agente pode trocar um diretório por um link no meio da
        varredura e ainda assim nada fora do workspace muda de dono. O `.git` antigo, na raiz do
        workspace, fica como está."""
        if os.geteuid() != 0:
            return
        uid, gid = run_identity(system)
        if uid == 0:
            return
        normalize_ownership(self.work_tree(system), uid, gid)

    def remove(self, system: System) -> None:
        shutil.rmtree(self.git_dir(system), ignore_errors=True)


def normalize_ownership(top: str, uid: int, gid: int) -> int:
    """Passa a `uid:gid` tudo que pertence ao root sob `top`, sem seguir link simbólico e sem
    entrar em `top/.git`. Devolve quantas entradas mudaram de dono."""
    if not _is_real_dir(top):
        return 0
    changed = 0
    top_fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(top_fd).st_uid == 0:
            os.fchown(top_fd, uid, gid)
            changed += 1
    finally:
        os.close(top_fd)
    for root, dirs, files, dirfd in os.fwalk(top, follow_symlinks=False):
        if os.path.normpath(root) == os.path.normpath(top) and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            try:
                st = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
                if st.st_uid == 0:
                    os.chown(name, uid, gid, dir_fd=dirfd, follow_symlinks=False)
                    changed += 1
            except FileNotFoundError:
                continue  # removido no meio da varredura
    return changed


def _is_real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _copy_regular_file(src: str, dst: str) -> bool:
    """Copia `src` só se for arquivo regular — abre sem seguir link simbólico."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as fsrc:
        if not stat.S_ISREG(os.fstat(fsrc.fileno()).st_mode):
            return False
        with open(dst, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
    os.chmod(dst, 0o444)
    return True


def get_backend() -> GitBackend:
    if get_settings().provisioning_driver == "kubernetes":
        from .drivers.kubernetes_driver import KubernetesGitBackend

        return KubernetesGitBackend()
    return DockerGitBackend()
