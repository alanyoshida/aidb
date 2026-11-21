"""Invocação do git contra o remoto e teste de conexão (change add-system-git-remote, tarefas 3.4 e
3.5), contra o servidor git por SSH da fixture."""

import os

import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture()
def linked(docker_env, clean_db, git_ssh_server, monkeypatch):
    """Sistema configurado para o repositório da fixture, com a identidade do servidor confirmada."""
    from appaiforge import auth, git_sync
    from appaiforge.config import get_settings
    from appaiforge.models import UserType
    from appaiforge.services import git_remote
    from appaiforge.services.systems import create_system

    monkeypatch.setenv("APPAIFORGE_GIT_RELAYS_DIR", str(docker_env / "relays"))
    get_settings.cache_clear()
    secret_dirs = docker_env / "secret-dirs"
    secret_dirs.mkdir()
    # diretórios de chave num lugar conhecido, para conferir que nada sobra depois da operação
    import tempfile

    monkeypatch.setattr(git_sync, "_secret_dir", lambda: tempfile.mkdtemp(prefix="aidb-ssh-", dir=str(secret_dirs)))
    owner = auth.create_user("conn@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Conn", f"conn-{os.urandom(3).hex()}")
    view = git_remote.configure(system, owner, url=git_ssh_server.url)
    scanned = git_sync.scan_host_key(git_remote.parse_remote_url(view["url"]))
    git_remote.confirm_host_key(system, owner, scanned.key)
    return system, owner, view, secret_dirs


def test_leitura_da_chave_do_servidor_bate_com_a_do_servidor(linked, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.services import git_remote

    system, owner, view, _ = linked
    scanned = git_sync.scan_host_key(git_remote.parse_remote_url(view["url"]))
    assert git_ssh_server.host_public_key().split()[1] in scanned.key
    assert scanned.fingerprints and all(fp.startswith("SHA256:") for fp in scanned.fingerprints)


def test_chave_nao_cadastrada_da_acesso_negado_e_nao_deixa_arquivos(linked, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.services import git_remote

    system, owner, view, secret_dirs = linked
    with pytest.raises(git_sync.RemoteError) as exc:
        git_sync.check_access(system.slug, git_remote.load_secrets(system.id))
    assert exc.value.kind == "access_denied"
    assert list(secret_dirs.iterdir()) == [], "nenhum arquivo de chave sobra depois de uma falha"


def test_conexao_valida_lista_branches_sem_alterar_nada(linked, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.services import git_remote

    system, owner, view, secret_dirs = linked
    git_ssh_server.authorize(view["public_key"])
    git_ssh_server.init_repo(with_branches=("main", "homolog"))
    before = git_ssh_server.git("for-each-ref", "--format=%(refname) %(objectname)")
    assert sorted(git_sync.check_access(system.slug, git_remote.load_secrets(system.id))) == ["homolog", "main"]
    assert git_ssh_server.git("for-each-ref", "--format=%(refname) %(objectname)") == before
    assert list(secret_dirs.iterdir()) == [], "nenhum arquivo de chave sobra depois de um sucesso"


def test_servidor_com_outra_identidade_e_recusado(linked, git_ssh_server):
    from appaiforge import git_sync
    from appaiforge.services import git_remote

    system, owner, view, secret_dirs = linked
    git_ssh_server.authorize(view["public_key"])
    git_ssh_server.rotate_host_keys()
    with pytest.raises(git_sync.RemoteError) as exc:
        git_sync.check_access(system.slug, git_remote.load_secrets(system.id))
    assert exc.value.kind == "host_key_changed"
    assert list(secret_dirs.iterdir()) == []


def test_sem_identidade_confirmada_nao_conecta(docker_env, clean_db, git_ssh_server):
    from appaiforge import auth, git_sync
    from appaiforge.models import UserType
    from appaiforge.services import git_remote
    from appaiforge.services.systems import create_system

    owner = auth.create_user("conn2@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Conn2", f"conn2-{os.urandom(3).hex()}")
    git_remote.configure(system, owner, url=git_ssh_server.url)
    with pytest.raises(git_sync.RemoteError) as exc:
        git_sync.check_access(system.slug, git_remote.load_secrets(system.id))
    assert exc.value.kind == "host_key_changed"
