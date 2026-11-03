"""Serviço do diretório: usuários, grupos e vínculos (spec portal-identity).

Ações de gestão são restritas a administradores e sempre registradas na trilha
de auditoria (`services.audit`). Excluir um usuário desacopla o histórico (FK
nulável, e-mail preservado), remove vínculos/dados operacionais e transfere a
posse dos sistemas para o admin executor.
"""

from sqlalchemy import delete, select, update

from ..auth import create_user as _create_user
from ..db import session_scope
from ..models import (
    AgentRun,
    ChatSession,
    Checkpoint,
    GateDecision,
    Group,
    GroupMember,
    Guideline,
    ManagementAudit,
    Session as SessionModel,
    System,
    SystemGroup,
    TokenUsage,
    User,
    UserType,
)
from . import audit


class EmailTaken(Exception):
    pass


class NameTaken(Exception):
    pass


def _require_admin(actor: User | None) -> None:
    if actor is not None and not actor.is_admin:
        raise PermissionError("operação restrita a administradores")


def create_user_as_admin(email: str, password: str, user_type: str, actor: User | None = None) -> User:
    _require_admin(actor)
    user = _create_user(email, password, user_type)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="user.create", resource_type="user", resource_id=user.id,
        details={"email": user.email, "type": user.type.value},
    )
    return user


def set_user_active(email: str, active: bool, actor: User | None = None) -> None:
    _require_admin(actor)
    target = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one()
        user.active = active
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="user.active", resource_type="user", resource_id=target, details={"active": active},
    )


def update_user_type(email: str, user_type: str, actor: User) -> None:
    _require_admin(actor)
    target = email.strip().lower()
    if user_type not in [t.value for t in UserType]:
        raise ValueError(f"tipo inválido: {user_type}")
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one()
        old = user.type.value
        user.type = UserType(user_type)
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="user.type", resource_type="user",
        resource_id=target, details={"old": old, "new": user_type},
    )


def delete_user(email: str, actor: User) -> None:
    """Exclui o usuário: transfere sistemas, limpa vínculos/sessões e desacopla o histórico."""
    _require_admin(actor)
    target = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one_or_none()
        if user is None:
            raise KeyError("usuário não encontrado")
        systems = s.execute(select(System).where(System.owner_id == user.id)).scalars().all()
        transferred = [sys_.id for sys_ in systems]
        for sys_ in systems:
            sys_.owner_id = actor.id
        s.execute(delete(GroupMember).where(GroupMember.user_id == user.id))
        s.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
        # desacopla o histórico (FK nulável) preservando o e-mail já gravado
        s.execute(update(AgentRun).where(AgentRun.user_id == user.id).values(user_id=None, chat_session_id=None))
        s.execute(update(TokenUsage).where(TokenUsage.user_id == user.id).values(user_id=None))
        s.execute(update(Checkpoint).where(Checkpoint.author_id == user.id).values(author_id=None))
        s.execute(update(GateDecision).where(GateDecision.author_id == user.id).values(author_id=None))
        s.execute(update(ManagementAudit).where(ManagementAudit.actor_id == user.id).values(actor_id=None))
        s.execute(update(Guideline).where(Guideline.updated_by_id == user.id).values(updated_by_id=None))
        s.execute(delete(ChatSession).where(ChatSession.user_id == user.id))
        s.delete(user)
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="user.delete", resource_type="user",
        resource_id=target, details={"transferred_system_ids": transferred},
    )


def create_group(name: str, actor: User | None = None) -> Group:
    _require_admin(actor)
    with session_scope() as s:
        group = Group(name=name.strip())
        s.add(group)
        s.flush()
        s.expunge(group)
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="group.create", resource_type="group", resource_id=group.id, details={"name": group.name},
    )
    return group


def rename_group(group_name: str, new_name: str, actor: User) -> None:
    _require_admin(actor)
    clean = new_name.strip()
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        conflict = s.execute(select(Group.id).where(Group.name == clean, Group.id != group.id)).scalar_one_or_none()
        if conflict is not None:
            raise NameTaken(f"grupo '{clean}' já existe")
        old = group.name
        group.name = clean
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="group.rename", resource_type="group",
        resource_id=group_name, details={"old": old, "new": clean},
    )


def delete_group(group_name: str, actor: User) -> None:
    _require_admin(actor)
    clean = group_name.strip()
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == clean)).scalar_one_or_none()
        if group is None:
            raise KeyError("grupo não encontrado")
        s.execute(delete(SystemGroup).where(SystemGroup.group_id == group.id))
        s.execute(delete(GroupMember).where(GroupMember.group_id == group.id))
        s.delete(group)
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="group.delete", resource_type="group",
        resource_id=clean, details={},
    )


def add_member(group_name: str, email: str, actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one()
        exists = s.execute(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user.id)
        ).scalar_one_or_none()
        if exists is None:
            s.add(GroupMember(group_id=group.id, user_id=user.id))
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="group.member_add", resource_type="group", resource_id=group_name.strip(),
        details={"email": email.strip().lower()},
    )


def remove_member(group_name: str, email: str, actor: User) -> None:
    _require_admin(actor)
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one()
        s.execute(
            delete(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user.id)
        )
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="group.member_remove", resource_type="group",
        resource_id=group_name.strip(), details={"email": email.strip().lower()},
    )


def link_group_to_system(group_name: str, system_slug: str, actor: User | None = None) -> None:
    _require_admin(actor)
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        system = s.execute(select(System).where(System.slug == system_slug.strip())).scalar_one()
        exists = s.execute(
            select(SystemGroup).where(SystemGroup.group_id == group.id, SystemGroup.system_id == system.id)
        ).scalar_one_or_none()
        if exists is None:
            s.add(SystemGroup(group_id=group.id, system_id=system.id))
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="group.link", resource_type="group", resource_id=group_name.strip(),
        details={"system_slug": system_slug.strip()},
    )


def unlink_group_from_system(group_name: str, system_slug: str, actor: User) -> None:
    _require_admin(actor)
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        system = s.execute(select(System).where(System.slug == system_slug.strip())).scalar_one()
        s.execute(
            delete(SystemGroup).where(SystemGroup.group_id == group.id, SystemGroup.system_id == system.id)
        )
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="group.unlink", resource_type="group",
        resource_id=group_name.strip(), details={"system_slug": system_slug.strip()},
    )


def list_groups() -> list[tuple[str, list[str], list[str]]]:
    """[(nome, [emails], [slugs])] para a UI de admin."""
    with session_scope() as s:
        groups = s.execute(select(Group).order_by(Group.name)).scalars().all()
        out = []
        for g in groups:
            emails = s.execute(
                select(User.email).join(GroupMember, GroupMember.user_id == User.id).where(GroupMember.group_id == g.id)
            ).scalars().all()
            slugs = s.execute(
                select(System.slug).join(SystemGroup, SystemGroup.system_id == System.id).where(SystemGroup.group_id == g.id)
            ).scalars().all()
            out.append((g.name, sorted(emails), sorted(slugs)))
        return out


def list_users() -> list[tuple[str, str, bool]]:
    """[(email, tipo, ativo)] para a UI de admin."""
    with session_scope() as s:
        users = s.execute(select(User).order_by(User.email)).scalars().all()
        return [(u.email, u.type.value, u.active) for u in users]


def owned_system_count(email: str) -> int:
    """Quantos sistemas o usuário possui (para avisar antes de excluir)."""
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
        if user is None:
            return 0
        return len(s.execute(select(System.id).where(System.owner_id == user.id)).scalars().all())