"""Serviço de sistemas (spec system-management)."""

import re

from sqlalchemy import select

from ..db import session_scope
from ..edge import publish_app, unpublish_app
from ..models import System, SystemStatus, User
from ..rbac import can_create_systems
from ..security import generate_secret
from ..config import get_settings

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class SlugTaken(Exception):
    pass


class InvalidSlug(Exception):
    pass


class NotPermitted(Exception):
    pass


def create_system(user: User, name: str, slug: str, provider: str | None = None, model: str | None = None) -> System:
    """Cria o sistema; criador vira dono (spec: somente editor/admin)."""
    if not can_create_systems(user):
        raise NotPermitted("somente editores podem criar sistemas")
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise InvalidSlug("slug deve ser kebab-case: letras minúsculas, dígitos e hífen")
    settings = get_settings()
    with session_scope() as s:
        exists = s.execute(select(System.id).where(System.slug == slug)).scalar_one_or_none()
        if exists is not None:
            raise SlugTaken(f"slug '{slug}' já existe")
        system = System(
            name=name.strip(),
            slug=slug,
            owner_id=user.id,
            provider=provider or settings.default_provider,
            model=model or settings.default_model,
            status=SystemStatus.provisioning,
            status_message="",
            identity_secret=generate_secret(),
        )
        s.add(system)
        s.flush()
        s.expunge(system)
    return system


def get_system(system_id: str) -> System | None:
    with session_scope() as s:
        system = s.get(System, system_id)
        if system is not None:
            s.expunge(system)
        return system


def get_system_by_slug(slug: str) -> System | None:
    with session_scope() as s:
        system = s.execute(select(System).where(System.slug == slug)).scalar_one_or_none()
        if system is not None:
            s.expunge(system)
        return system


def set_status(system_id: str, status: SystemStatus, message: str = "") -> None:
    with session_scope() as s:
        system = s.get(System, system_id)
        assert system is not None
        system.status = status
        system.status_message = message


def set_provider(system_id: str, provider: str, model: str) -> None:
    with session_scope() as s:
        system = s.get(System, system_id)
        assert system is not None
        system.provider = provider
        system.model = model


def set_container(system_id: str, container_id: str) -> None:
    with session_scope() as s:
        system = s.get(System, system_id)
        assert system is not None
        system.container_id = container_id


def advertise_app(system: System) -> None:
    """Publica a rota da app no edge (chamado quando a app fica sadia)."""
    publish_app(system)


def unadvertise_app(slug: str) -> None:
    unpublish_app(slug)
