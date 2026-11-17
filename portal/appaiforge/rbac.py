"""Guardas de capacidade e visibilidade de sistemas (specs portal-identity, system-management)."""

from sqlalchemy import select

from .db import session_scope
from .models import Group, GroupMember, System, SystemGroup, User, UserType


def can_create_systems(user: User) -> bool:
    """Somente editores criam sistemas; admin também pode (acesso total)."""
    return user.type in (UserType.editor, UserType.admin)


def can_chat(user: User) -> bool:
    return user.type in (UserType.editor, UserType.admin)


def visible_system_ids(user: User) -> set[str]:
    """Sistemas que o usuário pode ver/acessar: dono, admin (todos), grupos.

    Aceita `User` ou `auth.Principal`. Pertença a grupos (change add-oidc-sso, D6):
    `group_names` ausente/None -> pelo banco (`group_members`, modo local); tupla de
    nomes (modo oidc) -> grupos cadastrados cujo nome casa exatamente (sensível a
    maiúsculas) com um nome vindo do token.
    """
    group_names = getattr(user, "group_names", None)
    with session_scope() as s:
        if user.type == UserType.admin:
            return set(s.execute(select(System.id)).scalars())
        owned = set(s.execute(select(System.id).where(System.owner_id == user.id)).scalars())
        if group_names is None:
            via_group_q = (
                select(SystemGroup.system_id)
                .join(GroupMember, GroupMember.group_id == SystemGroup.group_id)
                .where(GroupMember.user_id == user.id)
            )
        elif group_names:
            via_group_q = (
                select(SystemGroup.system_id)
                .join(Group, Group.id == SystemGroup.group_id)
                .where(Group.name.in_(list(group_names)))
            )
        else:
            return owned
        return owned | set(s.execute(via_group_q).scalars())


def can_access_system(user: User, system_id: str) -> bool:
    if user.type == UserType.admin:
        return True
    return system_id in visible_system_ids(user)


def can_manage_system(user: User, system: System) -> bool:
    """Dono ou admin — gestão de conexões, guidelines de sistema, rollback."""
    if user.type == UserType.admin:
        return True
    return system.owner_id == user.id


def group_names_of(user: User) -> list[str]:
    """Nomes dos grupos cadastrados do usuário — entregues à app na identidade (D9).

    Modo local: pela tabela de membros. Modo oidc: nomes do token que casam com um grupo
    cadastrado (os demais não têm efeito no portal e não são repassados)."""
    group_names = getattr(user, "group_names", None)
    with session_scope() as s:
        if group_names is None:
            q = (
                select(Group.name)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.user_id == user.id)
            )
        elif group_names:
            q = select(Group.name).where(Group.name.in_(list(group_names)))
        else:
            return []
        return sorted(s.execute(q).scalars())
