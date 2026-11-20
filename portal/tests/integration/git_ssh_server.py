"""Servidor git por SSH efêmero para os testes do repositório remoto (change add-system-git-remote,
tarefa 3.2). Container Alpine com sshd e um repositório bare por teste; o teste faz o papel do
GitLab e do humano que faz merge direto no remoto."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
import time
from dataclasses import dataclass, field

import docker

IMAGE = "aidb-test-git-ssh-server:3.24.3"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "git-ssh-server")
REPO_PATH = "time/app"


def ensure_image() -> None:
    client = docker.from_env()
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        client.images.build(path=FIXTURE_DIR, tag=IMAGE, rm=True)


def generate_keypair(directory: str, name: str = "id") -> tuple[str, str]:
    """(caminho da chave privada, linha da chave pública), gerados com ssh-keygen."""
    os.makedirs(directory, exist_ok=True)
    key = os.path.join(directory, name)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"teste-{name}", "-f", key], check=True)
    with open(key + ".pub") as f:
        return key, f.read().strip()


@dataclass
class GitSshServer:
    container: object
    port: int
    workdir: str
    authorized: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"ssh://git@127.0.0.1:{self.port}/{REPO_PATH}.git"

    def exec(self, *cmd: str, user: str = "git") -> str:
        code, out = self.container.exec_run(list(cmd), user=user, demux=False)
        text = (out or b"").decode()
        if code != 0:
            raise RuntimeError(f"{' '.join(cmd)}: {text}")
        return text.strip()

    def sh(self, script: str, user: str = "git") -> str:
        return self.exec("sh", "-c", script, user=user)

    def _write(self, path: str, content: str, mode: int = 0o600) -> None:
        data = content.encode()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(os.path.basename(path))
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
        self.container.put_archive(os.path.dirname(path), buf.getvalue())
        self.exec("chown", "git:git", path, user="root")

    def authorize(self, public_key: str) -> None:
        self.authorized.append(public_key)
        self._write("/home/git/.ssh/authorized_keys", "\n".join(self.authorized) + "\n")

    def revoke_all(self) -> None:
        self.authorized.clear()
        self._write("/home/git/.ssh/authorized_keys", "")

    def init_repo(self, *, with_branches: tuple[str, ...] = ()) -> None:
        """Repositório bare vazio; com `with_branches`, cada branch nasce de um commit inicial."""
        self.sh(f"rm -rf /srv/git/{REPO_PATH}.git && mkdir -p /srv/git/time "
                f"&& git init -q --bare -b main /srv/git/{REPO_PATH}.git")
        # `ssh://host/time/app.git` usa caminho absoluto; `git@host:time/app.git`, relativo ao HOME
        self.exec("ln", "-sfn", "/srv/git/time", "/home/git/time", user="root")
        self.exec("ln", "-sfn", "/srv/git/time", "/time", user="root")
        if with_branches:
            self.commit_as_human(with_branches[0], {"README.md": "repositório remoto\n"}, "commit inicial do remoto")
            for branch in with_branches[1:]:
                self.git("branch", branch, with_branches[0])

    def git(self, *args: str) -> str:
        return self.exec("git", "--git-dir", f"/srv/git/{REPO_PATH}.git", *args)

    def commit_as_human(self, branch: str, files: dict[str, str], message: str) -> str:
        """Commit feito direto no remoto (o papel de um merge request humano já mergeado)."""
        work = "/tmp/human"
        self.sh(f"rm -rf {work}")
        if self.git("for-each-ref", f"refs/heads/{branch}"):
            self.sh(f"git clone -q -b {branch} /srv/git/{REPO_PATH}.git {work}")
        else:
            self.sh(f"git init -q -b {branch} {work} && cd {work} "
                    f"&& git remote add origin /srv/git/{REPO_PATH}.git")
        for path, content in files.items():
            self._write_text(f"{work}/{path}", content)
        self.sh(f"cd {work} && git add -A && git -c user.name=humano -c user.email=humano@remoto "
                f"commit -q -m '{message}' && git push -q origin HEAD:refs/heads/{branch}")
        return self.git("rev-parse", f"refs/heads/{branch}")

    def _write_text(self, path: str, content: str) -> None:
        self.sh(f"mkdir -p \"$(dirname {path})\"")
        self._write(path, content, 0o644)

    def host_public_key(self) -> str:
        return self.exec("cat", "/etc/ssh/ssh_host_ed25519_key.pub", user="root")

    def rotate_host_keys(self) -> None:
        """Troca a identidade do servidor (simula outro servidor atendendo no mesmo endereço)."""
        self.sh("rm -f /etc/ssh/ssh_host_* && ssh-keygen -A >/dev/null && kill -HUP 1", user="root")
        time.sleep(1)

    def stop(self) -> None:
        self.container.pause()

    def start(self) -> None:
        self.container.unpause()


def start_server(workdir: str) -> GitSshServer:
    ensure_image()
    client = docker.from_env()
    container = client.containers.run(IMAGE, detach=True, ports={"22/tcp": ("127.0.0.1", None)},
                                      labels={"aidb.test": "git-ssh-server"})
    for _ in range(50):
        container.reload()
        bindings = container.attrs["NetworkSettings"]["Ports"].get("22/tcp")
        if bindings:
            port = int(bindings[0]["HostPort"])
            break
        time.sleep(0.2)
    server = GitSshServer(container=container, port=port, workdir=workdir)
    for _ in range(50):
        try:
            server.exec("test", "-f", "/etc/ssh/ssh_host_ed25519_key.pub", user="root")
            break
        except RuntimeError:
            time.sleep(0.2)
    server.init_repo()
    return server
