"""A própria fixture do servidor git por SSH (tarefa 3.2): clona e empurra com uma chave dela."""

import os
import subprocess

import pytest

pytestmark = [pytest.mark.integration]


def test_clona_e_empurra_com_chave_gerada(git_ssh_server, tmp_path):
    from git_ssh_server import generate_keypair

    key, public = generate_keypair(str(tmp_path / "keys"))
    git_ssh_server.authorize(public)
    git_ssh_server.init_repo(with_branches=("main", "homolog"))
    known = tmp_path / "known_hosts"
    known.write_text(f"[127.0.0.1]:{git_ssh_server.port} {git_ssh_server.host_public_key()}\n")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_SSH_COMMAND": f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes "
                              f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={known}"}
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-b", "homolog", git_ssh_server.url, str(clone)], check=True, env=env)
    (clone / "novo.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "novo"],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "homolog"], check=True, env=env)
    assert "novo.txt" in git_ssh_server.git("ls-tree", "--name-only", "homolog")

    git_ssh_server.revoke_all()
    denied = subprocess.run(["git", "ls-remote", git_ssh_server.url], env=env, capture_output=True, text=True)
    assert denied.returncode != 0 and "Permission denied" in denied.stderr
