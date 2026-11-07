"""Serviço de sistemas (spec system-management)."""

import logging
import re

from sqlalchemy import select

from .. import inference_token
from ..db import session_scope
from ..edge import publish_app, unpublish_app
from ..models import AgentRun, ChatSession, RunStatus, System, SystemStatus, User
from ..provisioning import decide_execution_mode
from ..rbac import can_create_systems, can_manage_system
from ..security import generate_secret
from ..config import get_settings
from . import audit

log = logging.getLogger(__name__)

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
    # Decidido aqui, não em provision_system: o modo de execução é fixado na
    # criação do sistema e fica imutável depois (spec container-lifecycle).
    # Pode levantar SandboxUnavailable (host sem Landlock, require_sandbox
    # ligado) — nesse caso o sistema não deve ser criado.
    execution_mode, sandbox_warning = decide_execution_mode()
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
            status_message=sandbox_warning,
            execution_mode=execution_mode,
            identity_secret=generate_secret(),
        )
        s.add(system)
        s.flush()
        s.expunge(system)
    audit.record(
        actor_id=user.id, actor_email=user.email, action="system.create", resource_type="system",
        resource_id=system.id, system_id=system.id, details={"name": system.name, "slug": system.slug},
    )
    return system


def rename_system(system: System, name: str, actor: User) -> None:
    """Renomeia o sistema (nome de exibição); o slug permanece imutável."""
    if not can_manage_system(actor, system):
        raise NotPermitted("somente o dono ou um admin podem renomear o sistema")
    old = system.name
    new_name = name.strip()
    with session_scope() as s:
        row = s.get(System, system.id)
        assert row is not None
        row.name = new_name
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="system.rename", resource_type="system",
        resource_id=system.id, system_id=system.id, details={"old": old, "new": new_name},
    )


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


def inference_context(system_id: str) -> dict | None:
    """Contexto consultado pelo broker: versão do token, provedor/modelo e run/sessão ativos."""
    from . import catalog

    with session_scope() as s:
        system = s.get(System, system_id)
        if system is None:
            return None
        run = s.execute(
            select(AgentRun)
            .where(
                AgentRun.system_id == system_id,
                AgentRun.status.in_([RunStatus.running, RunStatus.awaiting_approval]),
            )
            .order_by(AgentRun.created_at.desc())
        ).scalars().first()
        session = s.get(ChatSession, run.chat_session_id) if run and run.chat_session_id else None
        provider_def = catalog.get_provider(system.provider)
        # Nome canônico do deployment no LiteLLM (mesma regra de litellm_sync).
        litellm_model = (
            f"{provider_def['provider_id'] or provider_def['id']}/{system.model}"
            if provider_def
            else system.model
        )
        return {
            "system_id": system.id,
            "version": system.inference_token_version,
            "provider": system.provider,
            "model": system.model,
            "litellm_model": litellm_model,
            "run_id": run.id if run else None,
            "chat_session_id": run.chat_session_id if run else None,
            "session_revoked": bool(session.inference_revoked) if session else False,
        }


def revoke_session_inference(chat_session_id: str, actor: User) -> None:
    """Marca a inferência de uma sessão como revogada (broker passa a recusar)."""
    with session_scope() as s:
        session = s.get(ChatSession, chat_session_id)
        if session is None:
            raise ValueError("sessão não encontrada")
        system = s.get(System, session.system_id)
        if system is None:
            raise ValueError("sistema da sessão não encontrado")
        if not can_manage_system(actor, system):
            raise NotPermitted("somente o dono ou um admin podem revogar a inferência da sessão")
        session.inference_revoked = True
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="chat_session.revoke_inference",
        resource_type="chat_session", resource_id=chat_session_id, system_id=system.id, details={},
    )


def set_status(system_id: str, status: SystemStatus, message: str = "") -> None:
    with session_scope() as s:
        system = s.get(System, system_id)
        assert system is not None
        system.status = status
        system.status_message = message


def set_provider(system_id: str, provider: str, model: str, actor: User | None = None) -> None:
    if not provider or not (model or "").strip():
        raise ValueError("provedor e modelo são obrigatórios")
    with session_scope() as s:
        system = s.get(System, system_id)
        assert system is not None
        if actor is not None and not can_manage_system(actor, system):
            raise NotPermitted("somente o dono ou um admin podem alterar o provedor do sistema")
        system.provider = provider
        system.model = model.strip()
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="system.provider", resource_type="system",
        resource_id=system_id, system_id=system_id, details={"provider": provider, "model": model.strip()},
    )
    if actor is not None:
        _reprovision_async(system_id)


def _reprovision_async(system_id: str) -> None:
    """Aplica provedor/modelo ao container (o opencode.json é fixado na criação)."""
    import threading

    def work() -> None:
        try:
            from ..provisioning import provision_system, publish_app

            fresh = get_system(system_id)
            if fresh is not None:
                provision_system(fresh)
                publish_app(fresh)
        except Exception:
            log.exception("não foi possível aplicar o provedor ao sistema %s", system_id)

    threading.Thread(target=work, daemon=True, name=f"refresh-provider-{system_id}").start()


def revoke_inference_access(system_id: str, actor: User) -> str:
    """Revoga o token opaco de inferência do sistema (incrementa a versão).

    Apenas dono ou admin. A recriação do container aplica o novo token
    (a env de credencial é fixada na criação).
    """
    with session_scope() as s:
        system = s.get(System, system_id)
        if system is None:
            raise ValueError(f"sistema {system_id} não encontrado")
        if not can_manage_system(actor, system):
            raise NotPermitted("somente o dono ou um admin podem revogar o acesso de inferência")
    new_version, token = inference_token.rotate(system_id)
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="system.revoke_inference",
        resource_type="system", resource_id=system_id, system_id=system_id,
        details={"inference_version": new_version},
    )
    _reprovision_async(system_id)
    return token


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
