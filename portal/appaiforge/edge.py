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
    text = yaml.safe_dump(content, sort_keys=True)
    try:
        with open(path) as f:
            if f.read() == text:
                # mesma rota: não reescreve, senão o Traefik recarrega a cada passada da
                # reconciliação (change portal-reconcile-loop, D6)
                return
    except FileNotFoundError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
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
                        "loadBalancer": {"servers": [{"url": get_settings().portal_internal_url.rstrip("/")}]}
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


def edge_auth_address(slug: str) -> str:
    """Endpoint do portal que o forwardAuth do Traefik chama antes de cada requisição à app
    (change add-oidc-sso, D8). Usa o endereço interno do portal (rede Docker / Service)."""
    return f"{get_settings().portal_internal_url.rstrip('/')}/internal/edge/auth/{slug}"


EDGE_AUTH_RESPONSE_HEADERS = ["X-AIDB-Identity"]


def app_route_config(slug: str) -> dict:
    """Config dinâmica do Traefik para `/apps/<slug>`: forwardAuth (verifica sessão e acesso e
    injeta a identidade) ANTES do stripPrefix — o portal precisa ver o caminho original em
    `X-Forwarded-Uri` para mandar o usuário de volta à app depois do login."""
    return {
        "http": {
            "routers": {
                f"app-{slug}": {
                    "rule": f"PathPrefix(`/apps/{slug}`)",
                    "entryPoints": ["web"],
                    "service": f"app-{slug}",
                    "priority": 100,
                    "middlewares": [f"app-{slug}-auth", f"app-{slug}-strip"],
                }
            },
            "middlewares": {
                f"app-{slug}-auth": {
                    "forwardAuth": {
                        "address": edge_auth_address(slug),
                        # authResponseHeaders sobrescreve o header vindo do cliente: uma
                        # identidade forjada nunca chega à app (o 200 sempre o inclui).
                        "authResponseHeaders": list(EDGE_AUTH_RESPONSE_HEADERS),
                    }
                },
                f"app-{slug}-strip": {"stripPrefix": {"prefixes": [f"/apps/{slug}"]}},
            },
            "services": {
                f"app-{slug}": {
                    "loadBalancer": {"servers": [{"url": system_app_url(slug)}]}
                }
            },
        }
    }


def publish_app_docker(system: System) -> None:
    """Implementação Docker de `publish_app` (WebSocket passa direto pelo file provider) —
    chamada por `DockerProvisioningDriver.publish`, nunca direto."""
    _write(f"apps-{system.slug}.yml", app_route_config(system.slug))


def unpublish_app_docker(slug: str) -> None:
    """Implementação Docker de `unpublish_app` — chamada por `DockerProvisioningDriver.unpublish`,
    nunca direto."""
    path = os.path.join(get_settings().dynamic_config_dir, f"apps-{slug}.yml")
    if os.path.exists(path):
        os.remove(path)
        log.info("rota removida: %s", path)
