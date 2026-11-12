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
