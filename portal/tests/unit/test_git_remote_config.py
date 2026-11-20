"""Configuração do vínculo com o repositório remoto (change add-system-git-remote, tarefas 2.2-2.4)."""

import json

import pytest

from appaiforge import auth
from appaiforge.models import UserType
from appaiforge.services import git_remote
from appaiforge.services.git_remote import InvalidRemote, NotPermitted, parse_remote_url


@pytest.mark.parametrize("url, expected", [
    ("git@gitlab.exemplo.com:time/app.git", ("git", "gitlab.exemplo.com", None, "time/app")),
    ("ssh://git@gitlab.exemplo.com:2222/time/sub/app.git", ("git", "gitlab.exemplo.com", 2222, "time/sub/app")),
    ("ssh://gitlab.exemplo.com/time/app", ("git", "gitlab.exemplo.com", None, "time/app")),
    ("deploy@10.0.0.5:grupo/projeto.git", ("deploy", "10.0.0.5", None, "grupo/projeto")),
])
def test_enderecos_ssh_aceitos(url, expected):
    a = parse_remote_url(url)
    assert (a.user, a.host, a.port, a.path) == expected
    assert a.ssh_url().startswith("ssh://")


@pytest.mark.parametrize("url", [
    "ext::sh -c touch% /tmp/x",
    "file:///etc",
    "/srv/repo.git",
    "https://gitlab.com/time/app.git",
    "http://gitlab.com/time/app.git",
    "git@-oProxyCommand=evil:time/app.git",
    "ssh://-oProxyCommand=evil/time/app.git",
    "git@host:-upload-pack=evil",
    "git@host:../../etc/passwd",
    "git@host:time/app.git; rm -rf /",
    "",
    "ssh://git@host:99999/a/b",
])
def test_enderecos_recusados(url):
    with pytest.raises(InvalidRemote):
        parse_remote_url(url)


@pytest.mark.parametrize("name", ["", "-x", "/a", "a..b", "a//b", "a/", "a.lock", ".oculta", "com espaço", "a~1", "a^", "a:b"])
def test_branches_recusadas(name):
    with pytest.raises(InvalidRemote):
        git_remote.validate_branch(name, "teste")


def test_derivacao_do_endereco_da_api_e_do_projeto():
    a = parse_remote_url("git@gitlab.exemplo.com:time/app.git")
    assert git_remote.derive_api_url(a) == "https://gitlab.exemplo.com"
    assert git_remote.project_api_path(a) == "time%2Fapp"
    assert git_remote.validate_api_url("http://gitlab/") == "http://gitlab"
    with pytest.raises(InvalidRemote):
        git_remote.validate_api_url("ftp://gitlab")


@pytest.fixture()
def owner_and_system(clean_db):
    from appaiforge.services.systems import create_system

    owner = auth.create_user("dono-repo@t.local", "pw", UserType.editor.value)
    other = auth.create_user("outro-repo@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Repo", "repo-cfg")
    return owner, other, system


def test_padroes_de_branch_e_chave_publica(owner_and_system):
    owner, _, system = owner_and_system
    view = git_remote.configure(system, owner, url="git@gitlab.exemplo.com:time/app.git")
    assert view["working_branch"] == "homolog" and view["target_branch"] == "main"
    assert view["public_key"].startswith("ssh-ed25519 ")
    assert view["fingerprint"].startswith("SHA256:")
    assert view["effective_api_url"] == "https://gitlab.exemplo.com"
    assert view["enabled"] is False


def test_somente_quem_gerencia_configura(owner_and_system):
    _, other, system = owner_and_system
    with pytest.raises(NotPermitted):
        git_remote.ensure_remote(system, other)
    with pytest.raises(NotPermitted):
        git_remote.configure(system, other, url="git@h:a/b.git")


def test_ativar_exige_identidade_do_servidor_confirmada(owner_and_system):
    owner, _, system = owner_and_system
    git_remote.configure(system, owner, url="git@h:a/b.git")
    with pytest.raises(InvalidRemote, match="identidade do servidor"):
        git_remote.set_enabled(system, owner, True)


def test_branches_iguais_recusadas(owner_and_system):
    owner, _, system = owner_and_system
    with pytest.raises(InvalidRemote):
        git_remote.configure(system, owner, url="git@h:a/b.git", working_branch="main", target_branch="main")


def test_chaves_diferentes_por_sistema_e_troca_de_chave(owner_and_system):
    from appaiforge.services.systems import create_system

    owner, _, system = owner_and_system
    second = create_system(owner, "Repo2", "repo-cfg-2")
    k1 = git_remote.ensure_remote(system, owner)["public_key"]
    k2 = git_remote.ensure_remote(second, owner)["public_key"]
    assert k1 != k2
    assert git_remote.ensure_remote(system, owner)["public_key"] == k1, "abrir de novo não troca a chave"
    rotated = git_remote.rotate_key(system, owner)["public_key"]
    assert rotated != k1
    assert git_remote.load_secrets(system.id) is None  # sem endereço, nada a usar
    git_remote.configure(system, owner, url="git@h:a/b.git")
    secrets = git_remote.load_secrets(system.id)
    assert "BEGIN OPENSSH PRIVATE KEY" in secrets.private_key
    assert secrets.private_key not in repr(secrets)


def test_segredos_nunca_saem_nas_respostas_nem_na_auditoria(owner_and_system):
    from sqlalchemy import select

    from appaiforge.db import session_scope
    from appaiforge.models import ManagementAudit

    owner, _, system = owner_and_system
    git_remote.configure(system, owner, url="git@gitlab.exemplo.com:time/app.git")
    git_remote.rotate_key(system, owner)
    view = git_remote.set_api_token(system, owner, "tok-segredo-de-teste-123")
    secrets = git_remote.load_secrets(system.id)
    assert secrets.api_token == "tok-segredo-de-teste-123"
    dumped = json.dumps(view)
    assert "tok-segredo" not in dumped and "PRIVATE KEY" not in dumped
    assert view["has_api_token"] is True
    with session_scope() as s:
        rows = s.execute(select(ManagementAudit).where(ManagementAudit.system_id == system.id)).scalars().all()
        details = json.dumps([r.details for r in rows])
        actions = [r.action for r in rows]
    assert "tok-segredo" not in details and "PRIVATE KEY" not in details
    assert {"git_remote.key_create", "git_remote.configure", "git_remote.key_rotate", "git_remote.api_access_set"} <= set(actions)
    assert git_remote.remove_api_token(system, owner)["has_api_token"] is False


def test_endereco_de_criacao_de_mr_preenchido(owner_and_system):
    from appaiforge.db import session_scope
    from appaiforge.models import SystemGitRemote

    owner, _, system = owner_and_system
    git_remote.configure(system, owner, url="git@gitlab.exemplo.com:time/app.git", api_url="http://gitlab")
    with session_scope() as s:
        url = git_remote.create_mr_url(s.get(SystemGitRemote, system.id))
    assert url == ("http://gitlab/time/app/-/merge_requests/new"
                   "?merge_request%5Bsource_branch%5D=homolog&merge_request%5Btarget_branch%5D=main")
