"""Interface comum aos drivers de provisionamento (capability `container-driver-kubernetes`).

Cada driver materializa, do jeito próprio ao seu orquestrador, a mesma unidade de execução por
sistema (container do agente + sidecars `dbgate`/`httpsproxy`, compartilhando rede) e expõe o
mesmo contrato observável das capabilities `container-lifecycle` e `app-serving` — ver requirement
"Paridade observável entre drivers de provisionamento"."""

from typing import Protocol

from ..models import System


class UnknownDriver(Exception):
    """`settings.provisioning_driver` não corresponde a nenhum driver implementado."""


class ComputeUnitNotFound(Exception):
    """A unidade de execução (container ou Pod) do sistema não existe no backend do driver —
    equivalente driver-agnóstico de `docker.errors.NotFound` para o container principal."""


class ComputeUnitOwnedElsewhere(Exception):
    """Já existe uma unidade de execução com o nome do sistema, mas ela é de outro sistema ou de
    outra instalação do portal (change add-production-portal-install, D2). O portal não a
    remove nem a adota."""

    def __init__(self, name: str, owner: str):
        self.name, self.owner = name, owner
        super().__init__(
            f"o nome {name} já está em uso por {owner}; o portal não remove nem reaproveita "
            "container de outro dono (produção precisa de um host Docker próprio)"
        )


class WorkspaceWriteError(OSError):
    """Falha ao escrever no workspace de um sistema quando o driver não dá ao portal um caminho
    local/montado até ele (driver Kubernetes: a PVC só é alcançável via exec dentro do Pod —
    change `fix-k8s-workspace-materialize-delete`). Subclasse de `OSError` para que chamadores
    como `AgentQueue._execute` tratem essa falha da mesma forma que já tratam uma falha de escrita
    local sob o driver Docker."""


def app_exec_command(command: list[str], env: dict[str, str] | None, timeout: int) -> list[str]:
    """Comando de `exec_in_app` com o prazo aplicado dentro do container e as variáveis extras
    acrescentadas ao ambiente herdado (mesma forma nos dois drivers)."""
    extra = [f"{k}={v}" for k, v in (env or {}).items()]
    return ["timeout", str(timeout), "env", *extra, *command]


def files_tar(files: dict[str, bytes], uid: int = 1000, gid: int = 1000) -> bytes:
    """Tar com `files` na raiz, do usuário da app (mesma forma nos dois drivers)."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(data), 0o644, uid, gid
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class ProvisioningDriver(Protocol):
    def ensure_ready(self) -> None:
        """Garante que a infraestrutura compartilhada do driver existe (rede/namespace)."""
        ...

    def provision(self, system: System, *, env: dict[str, str], manifest: list[dict]) -> str:
        """Cria (ou recria) a unidade de execução do sistema e seus sidecars; devolve um
        identificador opaco a persistir em `system.container_id`."""
        ...

    def remove(self, system: System) -> None:
        """Remove a unidade de execução do sistema e seus sidecars (idempotente)."""
        ...

    def reconcile_one(self, system_id: str, slug: str) -> None:
        """Garante que a unidade de execução e os sidecars do sistema existem, recriando os
        sidecars ausentes; levanta `ComputeUnitNotFound` se a unidade principal não existir."""
        ...

    def refresh_https_allowlist(self, system: System) -> None:
        """Recria só o sidecar do proxy HTTP(S) de saída, com a allow-list recalculada."""
        ...

    def publish(self, system: System) -> None:
        """Garante que `/apps/{slug}` roteia até a unidade de execução do sistema (idempotente).
        Chamado sempre depois de `provision()` ter sucesso — nunca antes."""
        ...

    def unpublish(self, slug: str) -> None:
        """Remove o roteamento de `/apps/{slug}` (idempotente)."""
        ...

    def healthcheck_url(self, system: System) -> str:
        """URL interna (dentro da rede do driver) para verificar a saúde da app do sistema."""
        ...

    def is_healthy(self, slug: str) -> bool:
        """Sonda de saúde usada pelo monitor periódico (spec app-serving) — driver-específica
        porque nem toda rede do driver é alcançável por um processo HTTP rodando fora dela (o
        driver Kubernetes roda com o portal fora do cluster; `healthcheck_url()` aponta pra um
        nome DNS só resolvível de dentro)."""
        ...

    def exec_in_app(
        self, system: System, command: list[str], *, env: dict[str, str] | None = None, timeout: int = 600
    ) -> tuple[int, str, str]:
        """Executa `command` no container da app, com a identidade da app e o ambiente dele
        (proxy de saída incluso), e devolve (código, stdout, stderr). `env` acrescenta variáveis
        só a esse comando (change add-deploy-only-system, D5)."""
        ...

    def write_app_files(self, system: System, directory: str, files: dict[str, bytes]) -> None:
        """Grava `files` (nome → conteúdo) em `directory` dentro do container da app, como o
        usuário da app — para a implantação preparar `uv sync` fora do workspace (D5)."""
        ...
