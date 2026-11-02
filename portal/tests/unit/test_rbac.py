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
