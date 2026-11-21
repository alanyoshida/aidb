"""Tipo do sistema e papel da instalação (change add-deploy-only-system, tarefa 1.2)."""

import pytest

from appaiforge import auth
from appaiforge.models import DeploySettings, UserType
from appaiforge.services import systems


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("tipo@t.local", "pw", UserType.editor.value)


def _role(monkeypatch, role: str) -> None:
    monkeypatch.setenv("APPAIFORGE_INSTALLATION_ROLE", role)
    from appaiforge.config import get_settings

    get_settings.cache_clear()


def test_padrao_em_desenvolvimento_e_com_agente(editor, monkeypatch):
    _role(monkeypatch, "development")
    assert systems.create_system(editor, "A", "tipo-a").kind == "agent"


def test_so_implantacao_em_desenvolvimento_ganha_configuracao(editor, monkeypatch):
    from appaiforge.db import session_scope

    _role(monkeypatch, "development")
    system = systems.create_system(editor, "B", "tipo-b", kind="deploy_only")
    assert system.kind == "deploy_only"
    with session_scope() as s:
        settings = s.get(DeploySettings, system.id)
        assert (settings.tag_pattern, settings.mode, settings.detection) == ("v*", "manual", "polling")


def test_producao_usa_so_implantacao_por_padrao_e_recusa_agente(editor, monkeypatch):
    _role(monkeypatch, "production")
    assert systems.create_system(editor, "C", "tipo-c").kind == "deploy_only"
    with pytest.raises(systems.AgentNotAllowedHere):
        systems.create_system(editor, "D", "tipo-d", kind="agent")


def test_tipo_desconhecido_recusado(editor, monkeypatch):
    _role(monkeypatch, "development")
    with pytest.raises(ValueError):
        systems.create_system(editor, "E", "tipo-e", kind="outro")
