"""Guardas de capacidade e visibilidade de sistemas (specs portal-identity, system-management)."""

from sqlalchemy import select

from .db import session_scope
from .models import GroupMember, System, SystemGroup, User, UserType


def can_create_systems(user: User) -> bool:
    """Somente editores criam sistemas; admin também pode (acesso total)."""
    return user.type in (UserType.editor, UserType.admin)


def can_chat(user: User) -> bool:
    return user.type in (UserType.editor, UserType.admin)


def visible_system_ids(user: User) -> set[str]:
    """Sistemas que o usuário pode ver/acessar: dono, admin (todos), grupos."""
    with session_scope() as s:
        if user.type == UserType.admin:
            return set(s.execute(select(System.id)).scalars())
        owned = set(s.execute(select(System.id).where(System.owner_id == user.id)).scalars())
        via_group = set(
            s.execute(
                select(SystemGroup.system_id)
                .join(GroupMember, GroupMember.group_id == SystemGroup.group_id)
                .where(GroupMember.user_id == user.id)
            ).scalars()
        )
        return owned | via_group


def can_access_system(user: User, system_id: str) -> bool:
    if user.type == UserType.admin:
        return True
    return system_id in visible_system_ids(user)


def can_manage_system(user: User, system: System) -> bool:
    """Dono ou admin — gestão de conexões, guidelines de sistema, rollback."""
    if user.type == UserType.admin:
        return True
    return system.owner_id == user.id
