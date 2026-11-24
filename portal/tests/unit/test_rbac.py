"""Unitários de RBAC: guardas de capacidade e visibilidade de sistemas."""

import pytest

from appaiforge import auth
from appaiforge.models import System, SystemStatus, User, UserType
from appaiforge.rbac import (
    can_access_system,
    can_chat,
    can_create_systems,
    can_manage_system,
    visible_system_ids,
)
from appaiforge.security import generate_secret, hash_password
from appaiforge.services.directory import add_member, create_group, link_group_to_system
from appaiforge.services.systems import NotPermitted, SlugTaken, create_system


def _mk_user(email: str, user_type: UserType) -> User:
    return auth.create_user(email, "pw", user_type.value)


def _mk_system(owner: User, slug: str) -> System:
    return create_system(owner, name=f"Sistema {slug}", slug=slug)


@pytest.fixture()
def users(clean_db):
    return {
        "admin": _mk_user("admin@t.local", UserType.admin),
        "editor": _mk_user("editor@t.local", UserType.editor),
        "editor2": _mk_user("editor2@t.local", UserType.editor),
        "app_user": _mk_user("app@t.local", UserType.app_user),
    }


def test_somente_editor_e_admin_criam_sistemas(users):
    assert can_create_systems(users["editor"])
    assert can_create_systems(users["admin"])
    assert not can_create_systems(users["app_user"])


def test_app_user_nao_conversa_com_agente(users):
    assert can_chat(users["editor"])
    assert not can_chat(users["app_user"])


def test_criador_vira_dono(users):
    system = _mk_system(users["editor"], "erp")
    assert system.owner_id == users["editor"].id
    assert system.status == SystemStatus.provisioning


def test_app_user_tenta_criar_e_e_recusado(users):
    with pytest.raises(NotPermitted):
        create_system(users["app_user"], "Meu sistema", "meu-sistema")


def test_slug_duplicado_e_recusado(users):
    _mk_system(users["editor"], "erp")
    with pytest.raises(SlugTaken):
        create_system(users["editor2"], "Outro", "erp")


def test_admin_acessa_tudo_e_outros_conforme_vinculo(users):
    sys1 = _mk_system(users["editor"], "erp")
    _mk_system(users["editor2"], "crm")

    assert can_access_system(users["admin"], sys1.id)
    assert visible_system_ids(users["editor"]) == {sys1.id}
    assert visible_system_ids(users["app_user"]) == set()

    create_group("clientes")
    add_member("clientes", "app@t.local")
    link_group_to_system("clientes", "erp")

    assert visible_system_ids(users["app_user"]) == {sys1.id}
    assert can_manage_system(users["editor"], sys1)
    assert not can_manage_system(users["app_user"], sys1)


# --- Pertença a grupos vinda do token (change add-oidc-sso, D6) ---

def _oidc_principal(user: User, groups: tuple[str, ...]):
    from appaiforge.auth import Principal

    return Principal(
        id=user.id, email=user.email, type=UserType.app_user, theme="light-indigo",
        active=True, auth_method="oidc", break_glass=False, group_names=groups,
    )


def test_grupo_do_token_casa_pelo_nome_exato(users):
    _mk_system(users["editor"], "fin")
    create_group("financeiro")
    link_group_to_system("financeiro", "fin")
    sys_id = next(iter(visible_system_ids(users["editor"])))
    assert can_access_system(_oidc_principal(users["app_user"], ("financeiro",)), sys_id)
    assert not can_access_system(_oidc_principal(users["app_user"], ("Financeiro",)), sys_id)
    assert not can_access_system(_oidc_principal(users["app_user"], ("ti-infra",)), sys_id)
    assert not can_access_system(_oidc_principal(users["app_user"], ()), sys_id)


def test_no_modo_oidc_membros_do_banco_nao_contam(users):
    _mk_system(users["editor"], "rh")
    create_group("rh")
    link_group_to_system("rh", "rh")
    add_member("rh", "app@t.local")
    sys_id = next(iter(visible_system_ids(users["editor"])))
    # a mesma pessoa, entrando pelo IdP sem o grupo no token, não acessa
    assert not can_access_system(_oidc_principal(users["app_user"], ()), sys_id)
    assert can_access_system(users["app_user"], sys_id)


# --- Capacidade de DB Manager (change add-db-manager-role, D1) ---

def _set_db_manager(user: User, value: bool = True) -> User:
    from appaiforge.db import session_scope

    with session_scope() as s:
        s.get(User, user.id).db_manager = value
    user.db_manager = value
    return user


def test_catalogo_admin_sem_a_capacidade(users):
    from appaiforge.rbac import can_manage_catalog

    assert can_manage_catalog(users["admin"])


def test_catalogo_editor_com_a_capacidade(users):
    from appaiforge.rbac import can_manage_catalog

    assert can_manage_catalog(_set_db_manager(users["editor"]))


def test_catalogo_app_user_com_a_capacidade(users):
    from appaiforge.rbac import can_manage_catalog

    assert can_manage_catalog(_set_db_manager(users["app_user"]))


def test_catalogo_recusado_sem_a_capacidade(users):
    from appaiforge.rbac import can_manage_catalog

    assert not can_manage_catalog(users["editor"])
    assert not can_manage_catalog(users["app_user"])


def test_principal_local_le_a_capacidade_do_banco(users):
    _set_db_manager(users["editor"])
    token = auth.create_session(users["editor"].id)
    principal = auth.resolve_principal(token)
    assert principal.is_db_manager
    assert principal.type == UserType.editor
    assert not auth.resolve_principal(auth.create_session(users["editor2"].id)).is_db_manager


def test_principal_oidc_le_a_capacidade_do_snapshot(users):
    # no modo oidc vale o snapshot da sessão, não o indicador do usuário
    token = auth.create_session(
        users["app_user"].id, auth_method="oidc", user_type="editor", groups=[], db_manager=True,
    )
    principal = auth.resolve_principal(token)
    assert principal.is_db_manager and principal.type == UserType.editor
    _set_db_manager(users["editor2"])
    token2 = auth.create_session(users["editor2"].id, auth_method="oidc", user_type="editor", groups=[])
    assert not auth.resolve_principal(token2).is_db_manager
