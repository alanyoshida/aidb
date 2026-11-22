"""Republicação das rotas no boot sob o driver Kubernetes (change gateway-api-traefik-subchart,
D6): é o que faz a troca de modo de roteamento valer para os sistemas existentes."""

from unittest.mock import patch

import pytest

from appaiforge import auth
from appaiforge.config import get_settings
from appaiforge.models import SystemStatus, UserType
from appaiforge.services.systems import create_system, set_status


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("republica@test.local", "pw", UserType.editor.value)


@pytest.fixture()
def driver(monkeypatch):
    def use(name: str) -> None:
        monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", name)
        get_settings.cache_clear()

    yield use
    get_settings.cache_clear()


def _system(editor, slug: str, status: SystemStatus):
    system = create_system(editor, slug, slug)
    set_status(system.id, status, "")
    return system


def test_republica_so_os_sistemas_ativos(editor, driver):
    driver("kubernetes")
    _system(editor, "rep-ativo-a", SystemStatus.active)
    _system(editor, "rep-ativo-b", SystemStatus.active)
    for slug, status in (("rep-arq", SystemStatus.archived), ("rep-prov", SystemStatus.provisioning),
                         ("rep-erro", SystemStatus.error)):
        _system(editor, slug, status)

    with patch("appaiforge.provisioning.publish_app") as publish:
        from appaiforge.provisioning import republish_routes

        assert republish_routes() == 2
    assert sorted(call.args[0].slug for call in publish.call_args_list) == ["rep-ativo-a", "rep-ativo-b"]


def test_falha_num_sistema_nao_impede_os_outros(editor, driver):
    driver("kubernetes")
    _system(editor, "rep-quebra", SystemStatus.active)
    _system(editor, "rep-ok", SystemStatus.active)

    def publish(system):
        if system.slug == "rep-quebra":
            raise RuntimeError("API do cluster fora")

    with patch("appaiforge.provisioning.publish_app", side_effect=publish):
        from appaiforge.provisioning import republish_routes

        assert republish_routes() == 1


def test_driver_docker_nao_republica(editor, driver):
    driver("docker")
    _system(editor, "rep-docker", SystemStatus.active)
    with patch("appaiforge.provisioning.publish_app") as publish:
        from appaiforge.provisioning import republish_routes

        assert republish_routes() == 0
    publish.assert_not_called()
