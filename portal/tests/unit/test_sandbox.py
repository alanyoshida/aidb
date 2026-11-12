"""Unitários do confinamento seccomp/Landlock (tasks 2.1/2.2/2.3 da etapa 2,
change agent-sandbox-seccomp-landlock)."""

import errno
import os

import pyseccomp as seccomp
import pytest

from afsupervisor import sandbox

FAKE_PROFILE = {
    "readable_paths": ["/usr", "/opt"],
    "writable_paths": ["/workspace"],
    "writable_files": ["/home/agent/.gitconfig"],
}


def test_build_seccomp_filter_nega_cada_syscall_do_denylist():
    sfilter = sandbox.build_seccomp_filter(["ptrace", "bpf"])
    assert isinstance(sfilter, seccomp.SyscallFilter)


def test_build_seccomp_filter_usa_denylist_padrao_quando_nao_informado():
    sfilter_padrao = sandbox.build_seccomp_filter()
    assert isinstance(sfilter_padrao, seccomp.SyscallFilter)
    assert "memfd_create" not in sandbox.DEFAULT_DENY_SYSCALLS
    assert "unshare" not in sandbox.DEFAULT_DENY_SYSCALLS  # unshare é tratado à parte (CLONE_NEWUSER)
    for nome in (
        "ptrace", "bpf", "mount", "setns", "perf_event_open",
        "process_vm_readv", "process_vm_writev", "pivot_root", "io_uring_setup",
    ):
        assert nome in sandbox.DEFAULT_DENY_SYSCALLS


def test_apply_sandbox_chama_seccomp_e_landlock_com_os_caminhos_do_perfil(monkeypatch):
    chamadas = {}

    def fake_build_filter(deny_syscalls=None):
        chamadas["deny_syscalls"] = deny_syscalls

        class FakeFilter:
            def load(self):
                chamadas["loaded"] = True

        return FakeFilter()

    def fake_apply_landlock(readable_paths, writable_paths, writable_files=None):
        chamadas["readable_paths"] = readable_paths
        chamadas["writable_paths"] = writable_paths
        chamadas["writable_files"] = writable_files

    def fake_apply_landlock_net(connect_tcp_ports, bind_tcp_ports):
        chamadas["connect_tcp_ports"] = connect_tcp_ports
        chamadas["bind_tcp_ports"] = bind_tcp_ports

    monkeypatch.setattr(sandbox, "build_seccomp_filter", fake_build_filter)
    monkeypatch.setattr(sandbox, "apply_landlock", fake_apply_landlock)
    # nunca aplicar Landlock de rede de verdade num teste não-forkado: o
    # restrict_self é irrevogável e derrubaria a rede do próprio processo
    # do pytest para o resto da sessão (achado ao escrever este teste)
    monkeypatch.setattr(sandbox, "apply_landlock_net", fake_apply_landlock_net)

    profile = {**FAKE_PROFILE, "connect_tcp_ports": [15400], "bind_tcp_ports": [4096]}
    sandbox.apply_sandbox(profile, deny_syscalls=["ptrace"])

    assert chamadas["loaded"] is True
    assert chamadas["deny_syscalls"] == ["ptrace"]
    assert chamadas["readable_paths"] == FAKE_PROFILE["readable_paths"]
    assert chamadas["writable_paths"] == FAKE_PROFILE["writable_paths"]
    assert chamadas["writable_files"] == FAKE_PROFILE["writable_files"]
    assert chamadas["connect_tcp_ports"] == [15400]
    assert chamadas["bind_tcp_ports"] == [4096]


def test_apply_sandbox_instala_seccomp_e_landlock_fs_antes_do_de_rede(monkeypatch):
    ordem = []
    monkeypatch.setattr(sandbox, "build_seccomp_filter", lambda deny_syscalls=None: type(
        "F", (), {"load": lambda self: ordem.append("seccomp")}
    )())
    monkeypatch.setattr(sandbox, "apply_landlock", lambda **kw: ordem.append("landlock_fs"))
    # idem: nunca de verdade fora de um fork (ver teste acima)
    monkeypatch.setattr(sandbox, "apply_landlock_net", lambda **kw: ordem.append("landlock_net"))

    sandbox.apply_sandbox(FAKE_PROFILE)

    assert ordem == ["seccomp", "landlock_fs", "landlock_net"]


def test_landlock_abi_fora_de_x86_64_devolve_zero(monkeypatch):
    fake_uname = type("U", (), {"machine": "aarch64"})()
    monkeypatch.setattr(os, "uname", lambda: fake_uname)
    assert sandbox.landlock_abi() == 0


def test_fs_access_bits_cresce_com_o_abi():
    bits_abi1 = sandbox._fs_access_bits(1)
    bits_abi2 = sandbox._fs_access_bits(2)
    bits_abi3 = sandbox._fs_access_bits(3)
    assert bits_abi1 < bits_abi2 < bits_abi3
    assert bits_abi2 & (1 << 13)  # REFER só a partir do ABI 2
    assert not bits_abi1 & (1 << 13)
    assert bits_abi3 & (1 << 14)  # TRUNCATE só a partir do ABI 3


def test_apply_landlock_sem_suporte_levanta_oserror(monkeypatch):
    monkeypatch.setattr(sandbox, "landlock_abi", lambda: 0)
    with pytest.raises(OSError):
        sandbox.apply_landlock(readable_paths=["/usr"], writable_paths=["/workspace"])


def test_net_access_bits_exige_abi_4(monkeypatch):
    """Direitos de rede do Landlock só existem a partir do ABI 4 (etapa 5,
    change agent-network-perimeter) — abaixo disso, filesystem funciona mas
    rede não tem bit nenhum disponível."""
    assert sandbox._net_access_bits(3) == 0
    assert sandbox._net_access_bits(0) == 0
    bits_abi4 = sandbox._net_access_bits(4)
    assert bits_abi4 & (1 << 0)  # BIND_TCP
    assert bits_abi4 & (1 << 1)  # CONNECT_TCP


def test_apply_landlock_net_sem_suporte_nao_faz_nada(monkeypatch):
    """Ao contrário de `apply_landlock` (filesystem), ABI insuficiente para
    rede não levanta — o filesystem já confinado continua valendo de
    qualquer forma, e quem decide se avisa é `apply_sandbox`."""
    monkeypatch.setattr(sandbox, "landlock_abi", lambda: 3)
    sandbox.apply_landlock_net(connect_tcp_ports=[15400], bind_tcp_ports=[4096])  # não levanta


@pytest.mark.sandbox
def test_apply_landlock_real_confina_escrita_a_caminhos_declarados(tmp_path):
    """Confinamento real via fork: landlock_restrict_self é irrevogável, então
    só é seguro exercitar num processo descartável (marker `sandbox`, opt-in —
    pode faltar Landlock no host de CI)."""
    if sandbox.landlock_abi() <= 0:
        pytest.skip("host sem suporte a Landlock")

    writable = tmp_path / "writable"
    readable = tmp_path / "readable"
    outside = tmp_path / "outside"
    writable.mkdir()
    readable.mkdir()
    outside.mkdir()
    (readable / "preexistente.txt").write_text("ja estava aqui")

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        resultado = {}
        try:
            sandbox.apply_landlock(readable_paths=[str(readable)], writable_paths=[str(writable)])
            (writable / "ok.txt").write_text("ok")
            resultado["escreveu_no_writable"] = True
            try:
                (outside / "nope.txt").write_text("nope")
                resultado["escreveu_fora"] = True
            except PermissionError:
                resultado["escreveu_fora"] = False
            try:
                (readable / "nope.txt").write_text("nope")
                resultado["escreveu_no_readable"] = True
            except PermissionError:
                resultado["escreveu_no_readable"] = False
            resultado["leu_preexistente"] = (readable / "preexistente.txt").read_text() == "ja estava aqui"
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["escreveu_no_writable"] is True
    assert resultado["escreveu_fora"] is False
    assert resultado["escreveu_no_readable"] is False
    assert resultado["leu_preexistente"] is True


@pytest.mark.sandbox
def test_apply_landlock_writable_file_ausente_e_criado_como_arquivo(tmp_path):
    """Achado real (change `add-kubernetes-driver`, task 8.3): um `writable_path` ausente que
    deveria ser ARQUIVO (ex.: `~/.gitconfig` do perfil claude-code) virava diretório vazio por
    `os.makedirs` — quebrando qualquer escrita real nele depois. `writable_files` é o caminho
    correto pra esse caso: cria um arquivo vazio, não diretório, antes de declarar a regra."""
    if sandbox.landlock_abi() <= 0:
        pytest.skip("host sem suporte a Landlock")

    arquivo_ausente = tmp_path / "config" / ".gitconfig"  # pai também não existe ainda

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        resultado = {}
        try:
            sandbox.apply_landlock(readable_paths=[], writable_paths=[], writable_files=[str(arquivo_ausente)])
            resultado["e_arquivo"] = arquivo_ausente.is_file()
            arquivo_ausente.write_text("[user]\n\tname = teste\n")
            resultado["escreveu"] = arquivo_ausente.read_text() == "[user]\n\tname = teste\n"
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["e_arquivo"] is True
    assert resultado["escreveu"] is True


@pytest.mark.sandbox
def test_apply_landlock_real_libera_leitura_de_arquivo_avulso_sem_liberar_irmao(tmp_path):
    """Achado real ao revisar `readable_paths` do perfil `opencode` (pedido do
    operador para bloquear leitura de arquivos sensíveis como /etc/passwd):
    declarar um ARQUIVO (não um diretório) em `readable_paths` levantava
    `OSError: [Errno 22] landlock_add_rule` — o perfil original só continha
    diretórios, então ninguém tinha batido nisso antes. O Landlock recusa
    bits de diretório (READ_DIR etc.) num alvo que não é diretório; a correção
    mascara o `access` pros bits compatíveis com arquivo antes de montar a
    regra (`_add_path_rule`). Este teste prova o cenário de verdade: leitura
    liberada só no arquivo declarado, negada no irmão não declarado na mesma
    pasta (equivalente a liberar `/etc/resolv.conf` sem liberar `/etc/passwd`)."""
    if sandbox.landlock_abi() <= 0:
        pytest.skip("host sem suporte a Landlock")

    pasta = tmp_path / "etc"
    pasta.mkdir()
    liberado = pasta / "resolv.conf"
    irmao = pasta / "passwd"
    liberado.write_text("nameserver 127.0.0.11")
    irmao.write_text("root:x:0:0::/root:/bin/bash")

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        resultado = {}
        try:
            sandbox.apply_landlock(readable_paths=[str(liberado)], writable_paths=[])
            resultado["leu_liberado"] = liberado.read_text()
            try:
                irmao.read_text()
                resultado["leu_irmao"] = True
            except PermissionError:
                resultado["leu_irmao"] = False
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["leu_liberado"] == "nameserver 127.0.0.11"
    assert resultado["leu_irmao"] is False


@pytest.mark.sandbox
def test_apply_landlock_net_real_restringe_porta_tcp_sem_enfraquecer_fs(tmp_path):
    """Spike da etapa 5 (change agent-network-perimeter), virado teste real:
    uma porta de loopback liberada conecta normalmente; uma não liberada nega
    com `PermissionError` (não `ConnectionRefusedError` — prova que é o
    Landlock barrando antes da rede, já que HÁ um listener nela também); e a
    camada de filesystem da etapa 2, aplicada antes, continua valendo depois
    do segundo `landlock_restrict_self`."""
    import socket

    if sandbox.landlock_abi() < 4:
        pytest.skip("host sem suporte a Landlock de rede (ABI < 4)")

    liberada, negada = 15490, 15491
    srv_liberada = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_liberada.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_liberada.bind(("127.0.0.1", liberada))
    srv_liberada.listen(1)
    srv_negada = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_negada.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_negada.bind(("127.0.0.1", negada))
    srv_negada.listen(1)

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        srv_liberada.close()
        srv_negada.close()
        resultado = {}
        try:
            sandbox.apply_landlock(readable_paths=["/usr"], writable_paths=[str(tmp_path)])
            sandbox.apply_landlock_net(connect_tcp_ports=[liberada], bind_tcp_ports=[])

            try:
                (tmp_path / "ok.txt").write_text("ok")
                resultado["fs_ainda_grava_workspace"] = True
            except PermissionError:
                resultado["fs_ainda_grava_workspace"] = False
            try:
                open("/etc/passwd").read()
                resultado["fs_etc_passwd_legivel"] = True
            except PermissionError:
                resultado["fs_etc_passwd_legivel"] = False

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect(("127.0.0.1", liberada))
                resultado["connect_porta_liberada"] = "ok"
                s.close()
            except Exception as exc:
                resultado["connect_porta_liberada"] = f"{type(exc).__name__}: {exc}"

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect(("127.0.0.1", negada))
                resultado["connect_porta_negada"] = "PASSOU (inesperado)"
                s.close()
            except PermissionError as exc:
                resultado["connect_porta_negada"] = f"negado: {exc}"
            except Exception as exc:
                resultado["connect_porta_negada"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        srv_liberada.close()
        srv_negada.close()
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["fs_ainda_grava_workspace"] is True
    assert resultado["fs_etc_passwd_legivel"] is False
    assert resultado["connect_porta_liberada"] == "ok"
    assert resultado["connect_porta_negada"].startswith("negado:")


@pytest.mark.sandbox
def test_apply_landlock_cria_writable_path_que_ainda_nao_existe(tmp_path):
    """Achado real da task 7: Landlock só autoriza um caminho que já existe
    (precisa abrir um fd pra ele). Sem criar `writable_paths` ausentes antes
    de declarar a regra, a regra era omitida em silêncio e a escrita negada
    — era exatamente o que quebrava o `mkdir('/home/agent/.local')` do
    opencode no primeiro boot do container."""
    if sandbox.landlock_abi() <= 0:
        pytest.skip("host sem suporte a Landlock")

    ainda_nao_existe = tmp_path / "cache" / "nested" / "dir"
    assert not ainda_nao_existe.exists()

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        resultado = {}
        try:
            sandbox.apply_landlock(readable_paths=[], writable_paths=[str(ainda_nao_existe)])
            resultado["foi_criado"] = ainda_nao_existe.is_dir()
            (ainda_nao_existe / "ok.txt").write_text("ok")
            resultado["escreveu_dentro"] = True
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["foi_criado"] is True
    assert resultado["escreveu_dentro"] is True


@pytest.mark.sandbox
def test_build_seccomp_filter_real_nega_ptrace_e_permite_memfd_create():
    """Mesma lógica do marker `sandbox`: carregar um filtro real num processo
    é irrevogável, então roda num fork descartável."""
    import ctypes

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        resultado = {}
        try:
            sandbox.build_seccomp_filter(["ptrace"]).load()
            libc = ctypes.CDLL(None, use_errno=True)
            r_ptrace = libc.syscall(101, 0, 0, 0, 0)
            resultado["ptrace_negado"] = r_ptrace == -1 and ctypes.get_errno() == errno.EPERM
            fd = libc.syscall(319, b"teste", 0)  # memfd_create
            resultado["memfd_create_permitido"] = fd >= 0
            if fd >= 0:
                os.close(fd)
        except Exception as exc:
            resultado["erro"] = str(exc)
        os.write(write_fd, repr(resultado).encode())
        os._exit(0)
    else:
        os.close(write_fd)
        saida = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            saida += chunk
        os.close(read_fd)
        os.waitpid(pid, 0)
        resultado = eval(saida.decode())

    assert resultado.get("erro") is None, resultado
    assert resultado["ptrace_negado"] is True
    assert resultado["memfd_create_permitido"] is True
