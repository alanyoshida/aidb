"""Roteador de apps no edge (ADR 0002): única dona das rotas do Traefik.

A rota raiz do próprio portal (portal.yml) é sempre file-provider, escrita no startup — o portal
nunca é um Pod por sistema, não depende do driver de provisionamento ativo.

A rota por sistema (`/apps/{slug}`) é que muda por driver (change `add-kubernetes-driver`,
capability `container-driver-kubernetes`): `publish_app`/`unpublish_app` delegam ao driver
ativo. No driver Docker, isso continua sendo o file provider (`apps-<slug>.yml`, mesmo mecanismo
de sempre). No driver Kubernetes, o Traefik roda DENTRO do cluster como Ingress controller — o
driver cria/remove um Service + Ingress por sistema, não um arquivo.

Trocar path por subdomínio no futuro = mudar só este módulo (e o `publish`/`unpublish` de cada
driver).
"""

import logging
import os

import yaml

from .config import get_settings
from .models import System

log = logging.getLogger(__name__)

SYSTEM_CONTAINER_PREFIX = "appaiforge-sys"


def system_container_name(slug: str) -> str:
    return f"{SYSTEM_CONTAINER_PREFIX}-{slug}"


def system_app_url(slug: str) -> str:
    return f"http://{system_container_name(slug)}:{get_settings().app_port}"


def _write(file_name: str, content: dict) -> None:
    directory = get_settings().dynamic_config_dir
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, file_name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(content, f, sort_keys=True)
    os.replace(tmp, path)  # atômico: o watcher do Traefik nunca lê arquivo parcial
    log.info("rota publicada: %s", path)


def write_portal_router() -> None:
    """Rota raiz -> portal. Idempotente; chamada no startup."""
    _write(
        "portal.yml",
        {
            "http": {
                "routers": {
                    "portal": {
                        "rule": "PathPrefix(`/`)",
                        "entryPoints": ["web"],
                        "service": "portal",
                        "priority": 1,
                    }
                },
                "services": {
                    "portal": {
                        "loadBalancer": {"servers": [{"url": "http://portal:8080"}]}
                    }
                },
            }
        },
    )


def publish_app(system: System) -> None:
    """Publica /apps/<slug> -> unidade de execução do sistema. Delega ao driver ativo (change
    `add-kubernetes-driver`) — chamado sempre depois de `provision_system` ter sucesso."""
    from .drivers import get_driver

    get_driver().publish(system)


def unpublish_app(slug: str) -> None:
    """Remove a rota de /apps/<slug>. Delega ao driver ativo."""
    from .drivers import get_driver

    get_driver().unpublish(slug)


def publish_app_docker(system: System) -> None:
    """Implementação Docker de `publish_app` (WebSocket passa direto pelo file provider) —
    chamada por `DockerProvisioningDriver.publish`, nunca direto."""
    slug = system.slug
    _write(
        f"apps-{slug}.yml",
        {
            "http": {
                "routers": {
                    f"app-{slug}": {
                        "rule": f"PathPrefix(`/apps/{slug}`)",
                        "entryPoints": ["web"],
                        "service": f"app-{slug}",
                        "priority": 100,
                        "middlewares": [f"app-{slug}-strip"],
                    }
                },
                "middlewares": {
                    f"app-{slug}-strip": {"stripPrefix": {"prefixes": [f"/apps/{slug}"]}}
                },
                "services": {
                    f"app-{slug}": {
                        "loadBalancer": {"servers": [{"url": system_app_url(slug)}]}
                    }
                },
            }
        },
    )


def unpublish_app_docker(slug: str) -> None:
    """Implementação Docker de `unpublish_app` — chamada por `DockerProvisioningDriver.unpublish`,
    nunca direto."""
    path = os.path.join(get_settings().dynamic_config_dir, f"apps-{slug}.yml")
    if os.path.exists(path):
        os.remove(path)
        log.info("rota removida: %s", path)
