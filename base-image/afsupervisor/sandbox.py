"""Confinamento auto-imposto do processo do agente — seccomp + Landlock
(etapa 2 do roadmap de confinamento, capability `agent-sandbox`).

Ambos os mecanismos são auto-impostos e não-privilegiados: nenhum dos dois
exige root nem componente externo ao container, e nenhum processo confinado
tem como revertê-los depois de instalados.

Seccomp usa `pyseccomp` (wrapper sobre libseccomp). Landlock é chamado via
`ctypes` direto, porque não existe hoje um binding Python maduro e mantido
para ele — só o necessário (três syscalls, x86_64) está implementado aqui;
ver design.md da change `agent-sandbox-seccomp-landlock`.
"""

import ctypes
import errno
import os
import sys
import typing

if typing.TYPE_CHECKING:
    import pyseccomp as seccomp

DEFAULT_DENY_SYSCALLS = [
    "ptrace",
    "bpf",
    "mount",
    "setns",
    "perf_event_open",
    "process_vm_readv",
    "process_vm_writev",
    "pivot_root",
    "io_uring_setup",
]
"""Syscalls negadas por padrão para o agente e toda a árvore de processos que
ele gerar.

Não inclui `memfd_create`: o runtime Bun do opencode usa `memfd_create` para
a memória JIT compatível com W^X, e a alternativa (memory protection keys da
CPU) não está disponível em hosts sem suporte a PKU — bloquear quebraria o
próprio agente.

Não inclui `unshare`: ele é negado separadamente só para `CLONE_NEWUSER` (ver
`build_seccomp_filter`), porque `unshare` com outros flags é usado por
ferramentas legítimas (uv, npm) e negá-lo por completo quebraria mais do que
protegeria.
"""

_CLONE_NEWUSER = 0x10000000


def build_seccomp_filter(deny_syscalls: list[str] | None = None) -> "seccomp.SyscallFilter":
    """Filtro seccomp: ALLOW por padrão, ERRNO(EPERM) para o denylist.

    Não chama `.load()` — quem instala decide quando (facilita testar a
    construção do filtro sem instalar nada no processo de teste).

    Importa `pyseccomp` aqui dentro (não no topo do módulo): o portal importa
    este módulo só por `landlock_abi()`/`apply_landlock()` para decidir o
    modo de execução de um sistema novo, e nunca chama esta função — exigir
    `pyseccomp`/`libseccomp2` também na imagem do portal seria uma dependência
    sem uso real ali."""
    import pyseccomp as seccomp

    deny_syscalls = DEFAULT_DENY_SYSCALLS if deny_syscalls is None else deny_syscalls
    sfilter = seccomp.SyscallFilter(seccomp.ALLOW)
    for name in deny_syscalls:
        sfilter.add_rule(seccomp.ERRNO(errno.EPERM), name)
    sfilter.add_rule(
        seccomp.ERRNO(errno.EPERM),
        "unshare",
        seccomp.Arg(0, seccomp.MASKED_EQ, _CLONE_NEWUSER, _CLONE_NEWUSER),
    )
    return sfilter


# --- Landlock (ctypes direto; só x86_64, ver landlock_abi()) -----------------

_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# Bits de LANDLOCK_ACCESS_FS_*, com a versão de ABI mínima que cada um exige.
_FS_ACCESS_BITS_BY_ABI: list[tuple[int, int]] = [
    (1 << 0, 1),   # EXECUTE
    (1 << 1, 1),   # WRITE_FILE
    (1 << 2, 1),   # READ_FILE
    (1 << 3, 1),   # READ_DIR
    (1 << 4, 1),   # REMOVE_DIR
    (1 << 5, 1),   # REMOVE_FILE
    (1 << 6, 1),   # MAKE_CHAR
    (1 << 7, 1),   # MAKE_DIR
    (1 << 8, 1),   # MAKE_REG
    (1 << 9, 1),   # MAKE_SOCK
    (1 << 10, 1),  # MAKE_FIFO
    (1 << 11, 1),  # MAKE_BLOCK
    (1 << 12, 1),  # MAKE_SYM
    (1 << 13, 2),  # REFER
    (1 << 14, 3),  # TRUNCATE
]
_FS_READ_ONLY_BITS = (1 << 0) | (1 << 2) | (1 << 3)  # EXECUTE | READ_FILE | READ_DIR

# Direitos que o Landlock aceita para um arquivo comum — todos os outros bits
# de LANDLOCK_ACCESS_FS_* (READ_DIR, MAKE_*, REMOVE_*, REFER) só fazem
# sentido para diretórios (criar/remover uma entrada *dentro* deles, listar).
# `landlock_add_rule` devolve EINVAL se um bit de diretório for pedido para
# um caminho cujo inode não é diretório — achado real (etapa 2, revisão do
# /etc): o perfil original só tinha diretórios em `readable_paths`, nunca um
# arquivo avulso, então isto nunca disparava antes.
_FS_FILE_ONLY_BITS = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14)  # EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE


_LANDLOCK_RULE_NET_PORT = 2

# Bits de LANDLOCK_ACCESS_NET_*, com a versão de ABI mínima (direitos de rede
# só existem a partir do ABI 4 — etapa 5 do roadmap de confinamento, change
# agent-network-perimeter).
_NET_ACCESS_BITS_BY_ABI: list[tuple[int, int]] = [
    (1 << 0, 4),  # BIND_TCP
    (1 << 1, 4),  # CONNECT_TCP
]


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _NetPortAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("port", ctypes.c_uint64)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def landlock_abi() -> int:
    """Versão de ABI do Landlock suportada pelo kernel do host, ou 0 quando
    o kernel não suporta Landlock (syscall ausente ou nega com ENOSYS)."""
    if os.uname().machine != "x86_64":
        return 0
    libc = _libc()
    abi = libc.syscall(
        _LANDLOCK_CREATE_RULESET, None, 0, _LANDLOCK_CREATE_RULESET_VERSION
    )
    return abi if abi > 0 else 0


def _fs_access_bits(abi: int) -> int:
    """Todos os bits de acesso a arquivo que o ABI detectado suporta."""
    bits = 0
    for bit, min_abi in _FS_ACCESS_BITS_BY_ABI:
        if abi >= min_abi:
            bits |= bit
    return bits


def _net_access_bits(abi: int) -> int:
    """Todos os bits de acesso a rede que o ABI detectado suporta — 0 abaixo
    do ABI 4 (sem direitos de rede nenhum nesse kernel)."""
    bits = 0
    for bit, min_abi in _NET_ACCESS_BITS_BY_ABI:
        if abi >= min_abi:
            bits |= bit
    return bits


def apply_landlock(readable_paths: list[str], writable_paths: list[str]) -> None:
    """Cria um ruleset Landlock liberando leitura+execução em
    `readable_paths` e leitura+escrita em `writable_paths`, e aplica ao
    processo atual (`landlock_restrict_self`) — qualquer caminho fora dessas
    listas fica negado por padrão (Landlock é subtrativo) e a restrição é
    herdada por todo processo filho, de forma irrevogável.

    Um `writable_path` que ainda não existe é criado aqui (`os.makedirs`)
    antes de declarar sua regra: Landlock só consegue autorizar um caminho
    que já tem um inode para abrir (`O_PATH`), então sem isso a regra seria
    silenciosamente omitida e a escrita, negada — achado real da etapa 2
    (task 7): `/home/agent/.local` e os demais caminhos de cache do perfil
    `opencode` não existem no primeiro boot do container, e `mkdir` nesses
    caminhos falhava com `EACCES` até esta correção. `readable_paths` que
    não existem continuam ignorados silenciosamente (não faz sentido criar
    um caminho só para lê-lo)."""
    abi = landlock_abi()
    if abi <= 0:
        raise OSError("Landlock não suportado neste host (ABI 0)")

    libc = _libc()
    write_bits = _fs_access_bits(abi)
    read_bits = _FS_READ_ONLY_BITS & write_bits

    attr = _RulesetAttr(handled_access_fs=write_bits, handled_access_net=0)
    ruleset_fd = libc.syscall(
        _LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0
    )
    if ruleset_fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")

    try:
        for path, access in ((p, write_bits) for p in writable_paths):
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            _add_path_rule(libc, ruleset_fd, path, access)
        for path, access in ((p, read_bits) for p in readable_paths):
            _add_path_rule(libc, ruleset_fd, path, access)

        libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
        rc = libc.syscall(_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0)
        if rc != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(ruleset_fd)


def _add_path_rule(libc: ctypes.CDLL, ruleset_fd: int, path: str, access: int) -> None:
    if not os.path.exists(path):
        return
    if not os.path.isdir(path):
        access &= _FS_FILE_ONLY_BITS
    fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        rule = _PathBeneathAttr(allowed_access=access, parent_fd=fd)
        rc = libc.syscall(
            _LANDLOCK_ADD_RULE, ruleset_fd, _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0
        )
        if rc != 0:
            raise OSError(ctypes.get_errno(), f"landlock_add_rule({path})")
    finally:
        os.close(fd)


def apply_landlock_net(connect_tcp_ports: list[int], bind_tcp_ports: list[int]) -> None:
    """Segunda camada de Landlock, empilhada por cima da de filesystem
    (`apply_landlock`) — um `landlock_restrict_self` adicional intersecta
    com o ruleset já instalado, nunca o substitui (etapa 5 do roadmap de
    confinamento, change `agent-network-perimeter`): conexão TCP de saída
    só nas portas de `connect_tcp_ports` (o `agent_port` de cada conexão do
    proxy de gate de banco, mais a porta do broker quando habilitado — ver
    `provisioning.py`) e escuta só nas portas de `bind_tcp_ports` (a do
    próprio harness); qualquer outra porta fica negada pelo kernel antes de
    a conexão alcançar a rede, independente do endereço — é essa
    independência de endereço que fecha o bypass do proxy de gate: a
    mesma regra nega tanto `127.0.0.1:porta` quanto `host-real:porta`.

    Sem suporte de ABI (abaixo de 4, só filesystem) não instala nada e
    devolve silenciosamente — chamador decide se avisa (ver `apply_sandbox`);
    não é um erro porque o filesystem já confinado por `apply_landlock`
    continua valendo de qualquer forma."""
    abi = landlock_abi()
    access_bits = _net_access_bits(abi)
    if access_bits == 0:
        return

    libc = _libc()
    attr = _RulesetAttr(handled_access_fs=0, handled_access_net=access_bits)
    ruleset_fd = libc.syscall(
        _LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0
    )
    if ruleset_fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset(net)")

    bind_bits = access_bits & (1 << 0)
    connect_bits = access_bits & (1 << 1)
    try:
        for port in bind_tcp_ports:
            _add_net_rule(libc, ruleset_fd, port, bind_bits)
        for port in connect_tcp_ports:
            _add_net_rule(libc, ruleset_fd, port, connect_bits)

        rc = libc.syscall(_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0)
        if rc != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self(net)")
    finally:
        os.close(ruleset_fd)


def _add_net_rule(libc: ctypes.CDLL, ruleset_fd: int, port: int, access: int) -> None:
    if access == 0:
        return
    rule = _NetPortAttr(allowed_access=access, port=port)
    rc = libc.syscall(
        _LANDLOCK_ADD_RULE, ruleset_fd, _LANDLOCK_RULE_NET_PORT, ctypes.byref(rule), 0
    )
    if rc != 0:
        raise OSError(ctypes.get_errno(), f"landlock_add_rule(net, porta {port})")


def apply_sandbox(profile: dict, deny_syscalls: list[str] | None = None) -> None:
    """Instala seccomp e, em seguida, Landlock (filesystem e depois rede), a
    partir do perfil do agente.

    Seccomp primeiro: nenhuma das syscalls do denylist é necessária para
    instalar o Landlock, então a ordem não deixa nenhuma janela em que uma
    das duas camadas está ativa e a outra não deveria estar. Filesystem antes
    de rede porque é o que já está validado em produção desde a etapa 2;
    rede empilha por cima sem alterá-lo (D1 do design da etapa 5)."""
    build_seccomp_filter(deny_syscalls).load()
    apply_landlock(
        readable_paths=profile.get("readable_paths", []),
        writable_paths=profile.get("writable_paths", []),
    )
    if landlock_abi() < 4:
        print(
            "[afsupervisor] ABI do Landlock abaixo de 4: confinamento de rede "
            "não instalado (filesystem segue confinado normalmente)",
            file=sys.stderr,
        )
        return
    apply_landlock_net(
        connect_tcp_ports=profile.get("connect_tcp_ports", []),
        bind_tcp_ports=profile.get("bind_tcp_ports", []),
    )
