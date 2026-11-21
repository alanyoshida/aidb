"""Identidade da instalação (change add-production-portal-install, task 1.2)."""

from appaiforge import auth, auth_mode, installation
from appaiforge.db import session_scope
from appaiforge.models import PortalInstance


def _recorded() -> str | None:
    with session_scope() as s:
        row = s.get(PortalInstance, 1)
        return row.installation_id if row else None


def test_banco_vazio_ganha_identificador(clean_db):
    auth_mode.check_on_boot()
    value = _recorded()
    assert value and len(value) == 32
    assert installation.installation_id() == value


def test_reinicio_mantem_o_identificador(clean_db):
    auth_mode.check_on_boot()
    first = _recorded()
    installation.reset_cache()
    auth_mode.check_on_boot()
    assert _recorded() == first
    assert installation.installation_id() == first


def test_bancos_diferentes_tem_identificadores_diferentes(clean_db):
    auth_mode.check_on_boot()
    first = _recorded()
    with session_scope() as s:
        s.delete(s.get(PortalInstance, 1))
    installation.reset_cache()
    auth_mode.check_on_boot()
    assert _recorded() != first


def test_linha_antiga_sem_identificador_e_completada(clean_db):
    user = auth.create_user("antigo@t.local", "pw", "admin")
    with session_scope() as s:
        s.add(PortalInstance(id=1, auth_mode="local", installation_id=None))
    assert auth_mode.check_on_boot() == "local"
    assert _recorded()
    with session_scope() as s:
        from appaiforge.models import User

        assert s.get(User, user.id) is not None


def test_sem_boot_o_identificador_e_criado_sob_demanda(clean_db):
    value = installation.installation_id()
    assert value == _recorded()
