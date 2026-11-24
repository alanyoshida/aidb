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
    ObservedIdpGroup,
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


class ManagedByIdp(PermissionError):
    """Operação de usuário/pertença indisponível no modo oidc: pertence ao IdP."""


class ProtectedUser(PermissionError):
    """O admin break-glass é definido só por ENV e não é gerenciável pela UI."""


def _require_local_mode() -> None:
    from ..auth_mode import is_oidc

    if is_oidc():
        raise ManagedByIdp("no modo oidc, usuários e membros de grupo são geridos pelo IdP")


def _reject_breakglass(user: User) -> None:
    if user.break_glass:
        raise ProtectedUser("o admin break-glass é definido por configuração e não pode ser alterado")


def sync_breakglass() -> None:
    """Aplica a configuração do break-glass no boot (D7).

    Configurado -> upsert do usuário com `break_glass=True`, `type=admin`, ativo, sem
    grupos e com o hash de senha da ENV. Qualquer outro usuário marcado como
    break-glass (ENV removida ou e-mail trocado) é desativado e perde as sessões.
    """
    from ..config import get_settings

    settings = get_settings()
    email = settings.breakglass_email.strip().lower()
    pw_hash = settings.breakglass_password_hash.strip()
    with session_scope() as s:
        if email and pw_hash:
            user = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None:
                user = User(email=email, type=UserType.admin)
                s.add(user)
            user.password_hash = pw_hash
            user.type = UserType.admin
            user.active = True
            user.break_glass = True
            s.flush()
            s.execute(delete(GroupMember).where(GroupMember.user_id == user.id))
            keep_id = user.id
        else:
            keep_id = None
        stale = s.execute(
            select(User).where(User.break_glass.is_(True), User.id != (keep_id or ""))
        ).scalars().all()
        for old in stale:
            old.active = False
            s.execute(delete(SessionModel).where(SessionModel.user_id == old.id))


def is_breakglass_email(email: str) -> bool:
    """True se o e-mail é o do admin break-glass configurado por ENV."""
    from ..config import get_settings

    configured = get_settings().breakglass_email.strip().lower()
    return bool(configured) and email.strip().lower() == configured


def _require_admin(actor: User | None) -> None:
    if actor is not None and not actor.is_admin:
        raise PermissionError("operação restrita a administradores")


def create_user_as_admin(
    email: str, password: str, user_type: str, actor: User | None = None, db_manager: bool = False,
) -> User:
    _require_admin(actor)
    _require_local_mode()
    user = _create_user(email, password, user_type)
    if db_manager:
        with session_scope() as s:
            s.get(User, user.id).db_manager = True
        user.db_manager = True
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="user.create", resource_type="user", resource_id=user.id,
        details={"email": user.email, "type": user.type.value, "db_manager": db_manager},
    )
    return user


def set_user_active(email: str, active: bool, actor: User | None = None) -> None:
    _require_admin(actor)
    _require_local_mode()
    target = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one()
        _reject_breakglass(user)
        user.active = active
    audit.record(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None,
        action="user.active", resource_type="user", resource_id=target, details={"active": active},
    )


def set_db_manager(email: str, value: bool, actor: User) -> None:
    """Concede ou retira a capacidade de DB Manager (change add-db-manager-role, D1).

    Só admin, só no modo local — no oidc a capacidade vem do papel `db_manager` do token.
    O break-glass é admin e já gere o catálogo, então não é alterável aqui. Retirar a
    capacidade não mexe nas conexões nem nas autorizações que a pessoa criou."""
    _require_admin(actor)
    _require_local_mode()
    target = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one()
        _reject_breakglass(user)
        if bool(user.db_manager) == value:
            return
        user.db_manager = value
    audit.record(
        actor_id=actor.id, actor_email=actor.email,
        action="user.db_manager.grant" if value else "user.db_manager.revoke",
        resource_type="user", resource_id=target, details={"db_manager": value},
    )


def update_user_type(email: str, user_type: str, actor: User) -> None:
    _require_admin(actor)
    _require_local_mode()
    target = email.strip().lower()
    if user_type not in [t.value for t in UserType]:
        raise ValueError(f"tipo inválido: {user_type}")
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one()
        _reject_breakglass(user)
        old = user.type.value
        user.type = UserType(user_type)
    audit.record(
        actor_id=actor.id, actor_email=actor.email, action="user.type", resource_type="user",
        resource_id=target, details={"old": old, "new": user_type},
    )


def delete_user(email: str, actor: User) -> None:
    """Exclui o usuário: transfere sistemas, limpa vínculos/sessões e desacopla o histórico."""
    _require_admin(actor)
    _require_local_mode()
    target = email.strip().lower()
    with session_scope() as s:
        user = s.execute(select(User).where(User.email == target)).scalar_one_or_none()
        if user is None:
            raise KeyError("usuário não encontrado")
        _reject_breakglass(user)
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
    _require_local_mode()
    with session_scope() as s:
        group = s.execute(select(Group).where(Group.name == group_name.strip())).scalar_one()
        user = s.execute(select(User).where(User.email == email.strip().lower())).scalar_one()
        _reject_breakglass(user)
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
    _require_local_mode()
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


# --- Modo oidc: grupos casam pelo nome com o claim do token (change add-oidc-sso) ---

OIDC_RENAME_WARNING = (
    "No modo SSO, usuários só casam com o grupo se o nome for idêntico (inclusive "
    "maiúsculas) ao do grupo no IdP. Renomear aqui sem renomear lá corta o acesso."
)


def rename_warning() -> str | None:
    """Aviso exibido ao renomear grupo (só no modo oidc)."""
    from ..auth_mode import is_oidc

    return OIDC_RENAME_WARNING if is_oidc() else None


def suggested_group_names() -> list[str]:
    """Nomes vistos em tokens que ainda não são grupos cadastrados (mais recentes primeiro)."""
    with session_scope() as s:
        registered = set(s.execute(select(Group.name)).scalars())
        seen = s.execute(
            select(ObservedIdpGroup.name).order_by(ObservedIdpGroup.last_seen_at.desc())
        ).scalars().all()
    return [name for name in seen if name not in registered]


def group_name_hint(name: str) -> str | None:
    """Aviso ao cadastrar, no modo oidc, um nome de grupo nunca visto em token."""
    from ..auth_mode import is_oidc

    clean = (name or "").strip()
    if not clean or not is_oidc():
        return None
    with session_scope() as s:
        if s.get(ObservedIdpGroup, clean) is not None:
            return None
    return (
        f"Nenhum usuário com o grupo '{clean}' entrou ainda. Confira se o nome é idêntico "
        "ao do IdP — o cadastro é aceito mesmo assim."
    )


def list_users_overview() -> list[dict]:
    """Usuários para a listagem do admin, com último login e marca de break-glass."""
    with session_scope() as s:
        users = s.execute(select(User).order_by(User.email)).scalars().all()
        return [
            {
                "email": u.email, "type": u.type.value, "active": u.active,
                "last_login_at": u.last_login_at, "break_glass": u.break_glass,
                "db_manager": bool(u.db_manager),
            }
            for u in users
        ]
