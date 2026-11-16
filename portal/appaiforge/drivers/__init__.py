"""Driver de provisionamento ativo, selecionável por configuração (etapa 8 do roadmap de
confinamento, change `add-kubernetes-driver`; capability `container-driver-kubernetes`).

`get_driver()` resolve o driver configurado (`settings.provisioning_driver`) sob demanda — nunca
num dict de módulo nem num import de topo, pra não forçar a dependência do cliente Kubernetes
(instalada só quando o driver `kubernetes` é usado) em quem só provisiona via Docker."""

from .base import ComputeUnitNotFound, ProvisioningDriver, UnknownDriver, WorkspaceWriteError

__all__ = ["ComputeUnitNotFound", "ProvisioningDriver", "UnknownDriver", "WorkspaceWriteError", "get_driver"]


def get_driver() -> ProvisioningDriver:
    from ..config import get_settings

    name = get_settings().provisioning_driver
    if name == "docker":
        from .docker_driver import DockerProvisioningDriver

        return DockerProvisioningDriver()
    if name == "kubernetes":
        from .kubernetes_driver import KubernetesProvisioningDriver

        return KubernetesProvisioningDriver()
    raise UnknownDriver(f"driver de provisionamento '{name}' desconhecido")
