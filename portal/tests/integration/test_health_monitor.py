"""Monitor de saúde: transições de estado (task 6.4).

A sonda real (DNS da rede Docker) só funciona de dentro da rede — em produção
o portal é container na rede e o E2E valida a reachability real. Aqui a sonda
é controlada para exercitar as transições do spec contra banco real.
"""

import pytest

pytestmark = pytest.mark.integration


def _fake_driver(results: list[bool]):
    """Sonda controlada (change `add-kubernetes-driver`): a sonda em si virou
    responsabilidade do driver (`ProvisioningDriver.is_healthy`), então o teste troca o
    driver resolvido em vez de um `_probe` que não existe mais em `health_monitor`."""

    class _FakeDriver:
        def is_healthy(self, slug: str) -> bool:
            return results.pop(0)

    return _FakeDriver()


def test_monitor_marca_erro_e_recupera(system, docker_env, monkeypatch):
    from appaiforge import health_monitor
    from appaiforge.models import SystemStatus
    from appaiforge.provisioning import provision_system
    from appaiforge.services.systems import get_system, set_status

    provision_system(system)
    set_status(system.id, SystemStatus.active, "")

    # sonda controlada: 3 falhas e depois recuperação
    probe_results = [False, False, False, True, True]
    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: _fake_driver(probe_results))

    health_monitor.check_once()
    health_monitor.check_once()
    assert get_system(system.id).status == SystemStatus.active  # abaixo do threshold

    health_monitor.check_once()
    fresh = get_system(system.id)
    assert fresh.status == SystemStatus.error
    assert "app fora do ar" in (fresh.status_message or "")

    # sonda saudável de novo: volta a ativo sem intervenção, mensagem limpa
    health_monitor.check_once()
    fresh = get_system(system.id)
    assert fresh.status == SystemStatus.active
    assert fresh.status_message == ""


def test_sistema_que_nunca_esteve_saudavel_nao_e_marcado_como_app_fora_do_ar(system, docker_env, monkeypatch):
    """Sistema ainda provisionando não é alvo do monitor (só ativos)."""
    from appaiforge import health_monitor
    from appaiforge.models import SystemStatus
    from appaiforge.services.systems import get_system

    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: _fake_driver([False]))
    results = health_monitor.check_once()
    assert system.slug not in results  # status provisioning: fora do escopo
    assert get_system(system.id).status == SystemStatus.provisioning
