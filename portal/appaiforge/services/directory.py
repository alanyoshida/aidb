"""Serviço do diretório: usuários, grupos e vínculos (spec portal-identity)."""

from sqlalchemy import select

from ..auth import create_user as _create_user
from ..db import session_scope
from ..models import Group, GroupMember, System, SystemGroup, User


class EmailTaken(Exception):
    pass


def create_user_as_admin(email: str, password: str, user_type: str) -> User:
    return _create_user(email, password, user_type)


def set_user_active(email: str, active: bool) -> None:
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one()
        user.active = active


def create_group(name: str) -> Group:
    with session_scope() as s:
        group = Group(name=name.strip())
        s.add(group)
        s.flush()
        s.expunge(group)
        return group


def add_member(group_name: str, email: str) -> None:
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one()
        exists = s.execute(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user.id)
        ).scalar_one_or_none()
        if exists is None:
            s.add(GroupMember(group_id=group.id, user_id=user.id))


def link_group_to_system(group_name: str, system_slug: str) -> None:
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        system = s.execute(select(System).where(System.slug == system_slug.strip())).scalar_one()
        exists = s.execute(
            select(SystemGroup).where(SystemGroup.group_id == group.id, SystemGroup.system_id == system.id)
        ).scalar_one_or_none()
        if exists is None:
            s.add(SystemGroup(group_id=group.id, system_id=system.id))


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
