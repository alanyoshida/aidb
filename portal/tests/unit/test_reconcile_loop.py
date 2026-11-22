"""Unitários da change `portal-reconcile-loop`: trava por sistema, reconciliação que relê o estado e
isola falhas, laço na subida e periódico, e escrita idempotente da rota Docker."""

import importlib
import sys
import threading
import time

import pytest

from appaiforge import auth, provisioning
from appaiforge.drivers import ComputeUnitNotFound
from appaiforge.models import SystemStatus, UserType
from appaiforge.services.systems import create_system, get_system, set_status


@pytest.fixture()
def editor(clean_db):
    return auth.create_user("reconcile-loop@t.local", "pw", UserType.editor.value)


class _Driver:
    """Driver falso: grava as chamadas; `missing` são slugs sem unidade, `broken` levantam erro
    inesperado no `reconcile_one`."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.missing: set[str] = set()
        self.broken: set[str] = set()

    def reconcile_one(self, system_id, slug):
        self.calls.append(("reconcile_one", slug))
        if slug in self.broken:
            raise RuntimeError("API fora do ar")
        if slug in self.missing:
            raise ComputeUnitNotFound(slug)

    def remove(self, system):
        self.calls.append(("remove", system.slug))


@pytest.fixture()
def driver(monkeypatch):
    fake = _Driver()
    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: fake)
    monkeypatch.setattr(provisioning, "publish_app_by_slug", lambda slug: fake.calls.append(("publish", slug)))
    monkeypatch.setattr(provisioning, "_check_connections_health", lambda sid: fake.calls.append(("health", sid)))
    return fake


@pytest.fixture()
def recreated(monkeypatch):
    """`provision_system` falso (o de verdade passa pelo driver e escreve config): grava o slug e
    segura a trava do sistema, como o de verdade."""
    slugs: list[str] = []

    def fake_provision(system):
        with provisioning.system_operation_lock(system.id):
            slugs.append(system.slug)
        return "unit-id"

    monkeypatch.setattr(provisioning, "provision_system", fake_provision)
    return slugs


def _active(editor, slug, message=""):
    system = create_system(editor, slug, slug)
    set_status(system.id, SystemStatus.active, message)
    return system


# --- trava por sistema (task 1.1) -------------------------------------------------------------


def test_trava_por_sistema_e_reentrante_e_exclusiva_entre_threads():
    lock = provisioning.system_operation_lock("sys-a")
    assert provisioning.system_operation_lock("sys-a") is lock
    assert provisioning.system_operation_lock("sys-b") is not lock
    with lock:
        with provisioning.system_operation_lock("sys-a"):  # reentrância: não trava
            pass
        got: list[bool] = []
        t = threading.Thread(target=lambda: got.append(lock.acquire(blocking=False)))
        t.start()
        t.join()
        assert got == [False]


def test_provision_system_segura_a_trava_do_sistema(editor, monkeypatch):
    system = create_system(editor, "Trava", "trava-provision")
    seen: list[bool] = []

    class _Probe:
        def ensure_ready(self):
            pass

        def provision(self, sys_, *, env, manifest):
            # outra thread não consegue a trava enquanto o provisionamento roda
            t = threading.Thread(
                target=lambda: seen.append(provisioning.system_operation_lock(sys_.id).acquire(blocking=False))
            )
            t.start()
            t.join()
            return "unit"

    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: _Probe())
    monkeypatch.setattr(provisioning, "set_container", lambda *a: None)
    monkeypatch.setattr(provisioning, "write_opencode_config", lambda *a, **kw: None)
    monkeypatch.setattr(provisioning, "write_agent_profile", lambda *a, **kw: None)
    monkeypatch.setattr(provisioning, "_provider_env", lambda *a: {})
    monkeypatch.setattr(provisioning, "_connection_env", lambda *a: {})

    with provisioning.system_operation_lock(system.id):  # já segura: reentrante, não trava
        assert provisioning.provision_system(system) == "unit"
    assert seen == [False]


@pytest.mark.parametrize("operation", ["archive_system", "delete_system", "refresh_https_allowlist"])
def test_operacoes_sobre_a_unidade_esperam_a_trava(editor, monkeypatch, operation):
    system = create_system(editor, "Trava", f"trava-{operation.replace('_', '-')}")
    system.container_id = "unit"
    started = threading.Event()
    monkeypatch.setattr(provisioning, "stop_and_remove", lambda s: started.set())
    monkeypatch.setattr(provisioning, "unpublish_app", lambda slug: None)

    class _D:
        def refresh_https_allowlist(self, s):
            started.set()

    monkeypatch.setattr("appaiforge.drivers.get_driver", lambda: _D())
    if operation == "delete_system":
        monkeypatch.setattr("appaiforge.git_backend.get_backend", lambda: type("B", (), {"remove": lambda self, s: None})())

    lock = provisioning.system_operation_lock(system.id)
    lock.acquire()
    t = threading.Thread(target=lambda: getattr(provisioning, operation)(system))
    t.start()
    try:
        assert not started.wait(0.3), "a operação não esperou a trava"
    finally:
        lock.release()
    t.join(5)
    assert started.is_set()


# --- reconcile(): trava, estado relido, falhas isoladas, volta a ativo (tasks 1.2 e 1.3) --------


def test_sistema_ocupado_e_pulado_e_reconciliado_na_passada_seguinte(editor, driver):
    busy = _active(editor, "rl-ocupado")
    free = _active(editor, "rl-livre")
    lock = provisioning.system_operation_lock(busy.id)
    holder_ready, release = threading.Event(), threading.Event()

    def hold():
        with lock:
            holder_ready.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    holder_ready.wait(5)
    try:
        provisioning.reconcile()
    finally:
        release.set()
        t.join(5)
    assert ("reconcile_one", free.slug) in driver.calls
    assert ("reconcile_one", busy.slug) not in driver.calls
    assert ("health", busy.id) not in driver.calls

    provisioning.reconcile()
    assert ("reconcile_one", busy.slug) in driver.calls


def test_sistema_arquivado_depois_da_leitura_inicial_nao_e_recriado(editor, driver, recreated, monkeypatch):
    a = _active(editor, "rl-sistema-a")
    b = _active(editor, "rl-sistema-b")
    driver.missing = {a.slug, b.slug}
    archived: list = []
    original = provisioning._reconcile_system

    def archive_the_other_first(drv, system_id):
        # o primeiro sistema da passada arquiva o outro: a lista inicial já tinha os dois
        if not archived:
            other = b if system_id == a.id else a
            set_status(other.id, SystemStatus.archived, "")
            archived.append(other)
        return original(drv, system_id)

    monkeypatch.setattr(provisioning, "_reconcile_system", archive_the_other_first)
    provisioning.reconcile()

    late = archived[0]
    first = a if late is b else b
    assert recreated == [first.slug]
    assert ("reconcile_one", late.slug) not in driver.calls
    assert get_system(late.id).status == SystemStatus.archived


def test_sistemas_arquivados_e_em_provisionamento_sao_pulados(editor, driver):
    archived = _active(editor, "rl-arquivado")
    set_status(archived.id, SystemStatus.archived, "")
    provisioning_ = create_system(editor, "rl-provisionando", "rl-provisionando")  # nasce provisioning
    provisioning.reconcile()
    assert driver.calls == []
    assert get_system(provisioning_.id).status == SystemStatus.provisioning


def test_passada_publica_a_rota_de_sistemas_ativos_e_em_erro(editor, driver):
    """Design D7: a passada da subida substitui a republicação das rotas no boot da change
    gateway-api-traefik-subchart (troca de modo de roteamento), para ativos e em erro."""
    active = _active(editor, "rl-rota-ativo")
    failed = _active(editor, "rl-rota-erro")
    set_status(failed.id, SystemStatus.error, "falhou antes")

    provisioning.reconcile()

    published = {slug for call, slug in driver.calls if call == "publish"}
    assert published == {active.slug, failed.slug}


def test_erro_inesperado_num_sistema_nao_interrompe_a_passada_nem_muda_o_estado(editor, driver):
    broken = _active(editor, "rl-quebrado", "mensagem anterior")
    ok = _active(editor, "rl-ok")
    driver.broken = {broken.slug}

    provisioning.reconcile()

    assert ("reconcile_one", ok.slug) in driver.calls
    assert ("publish", ok.slug) in driver.calls
    after = get_system(broken.id)
    assert after.status == SystemStatus.active and after.status_message == "mensagem anterior"
    assert ("health", broken.id) in driver.calls  # saúde das conexões checada mesmo assim
    assert ("publish", broken.slug) not in driver.calls


def test_recriacao_bem_sucedida_volta_o_sistema_a_ativo(editor, driver, recreated):
    system = _active(editor, "rl-em-erro")
    set_status(system.id, SystemStatus.error, "reconciliação falhou: imagem ausente")
    driver.missing = {system.slug}

    provisioning.reconcile()

    assert recreated == [system.slug]
    assert ("publish", system.slug) in driver.calls
    after = get_system(system.id)
    assert after.status == SystemStatus.active and after.status_message == ""


def test_recriacao_que_falha_deixa_o_sistema_em_erro(editor, driver, monkeypatch):
    system = _active(editor, "rl-falha")
    driver.missing = {system.slug}

    def boom(s):
        raise RuntimeError("sem imagem")

    monkeypatch.setattr(provisioning, "provision_system", boom)
    provisioning.reconcile()
    after = get_system(system.id)
    assert after.status == SystemStatus.error
    assert after.status_message == "reconciliação falhou: sem imagem"


def test_portal_de_producao_remove_sistema_com_agente(editor, driver, monkeypatch):
    system = _active(editor, "rl-agente-prod")
    monkeypatch.setattr("appaiforge.services.systems.is_production", lambda: True)
    provisioning.reconcile()
    assert driver.calls == [("remove", system.slug)]
    after = get_system(system.id)
    assert after.status == SystemStatus.error and "produção" in after.status_message


# --- laço (task 2.1) --------------------------------------------------------------------------


def _counting_reconcile(monkeypatch, fail_first=False):
    calls: list[float] = []

    def fake():
        calls.append(time.monotonic())
        if fail_first and len(calls) == 1:
            raise RuntimeError("passada quebrou")

    monkeypatch.setattr(provisioning, "reconcile", fake)
    return calls


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_laco_faz_passada_imediata_e_depois_periodica(monkeypatch):
    calls = _counting_reconcile(monkeypatch)
    stop = threading.Event()
    thread = provisioning.start_reconcile_loop(interval=0.05, stop=stop)
    try:
        assert _wait_for(lambda: len(calls) >= 1, timeout=1)
        assert _wait_for(lambda: len(calls) >= 3)
    finally:
        stop.set()
        thread.join(2)
    assert not thread.is_alive()
    assert thread.daemon


def test_laco_com_intervalo_zero_faz_so_a_passada_da_subida(monkeypatch):
    calls = _counting_reconcile(monkeypatch)
    thread = provisioning.start_reconcile_loop(interval=0)
    thread.join(2)
    assert not thread.is_alive()
    assert len(calls) == 1


def test_laco_usa_o_intervalo_da_configuracao(monkeypatch):
    from appaiforge.config import get_settings

    monkeypatch.setenv("APPAIFORGE_RECONCILE_INTERVAL", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().reconcile_interval == 0
        calls = _counting_reconcile(monkeypatch)
        provisioning.start_reconcile_loop().join(2)
        assert len(calls) == 1
    finally:
        get_settings.cache_clear()
    from appaiforge.config import Settings

    assert Settings.model_fields["reconcile_interval"].default == 300.0


def test_passada_que_falha_nao_encerra_o_laco(monkeypatch):
    calls = _counting_reconcile(monkeypatch, fail_first=True)
    stop = threading.Event()
    thread = provisioning.start_reconcile_loop(interval=0.05, stop=stop)
    try:
        assert _wait_for(lambda: len(calls) >= 2)
    finally:
        stop.set()
        thread.join(2)


# --- subida do portal (task 2.2) --------------------------------------------------------------


def test_create_app_inicia_o_laco_sem_reconciliar_de_forma_sincrona(clean_db, monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(provisioning, "start_reconcile_loop", lambda *a, **kw: started.append("loop"))
    monkeypatch.setattr(provisioning, "reconcile", lambda: started.append("reconcile-sincrono"))
    monkeypatch.setattr("appaiforge.health_monitor.start_monitor", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.deploy.start_poller", lambda *a, **kw: None)
    monkeypatch.setattr("appaiforge.deploy.recover_interrupted", lambda: None)
    monkeypatch.setattr("appaiforge.telemetry.start_span_cleanup_timer", lambda: None)
    monkeypatch.setattr("appaiforge.installation.check_docker_host", lambda: None)
    monkeypatch.setattr("appaiforge.services.litellm_sync.sync_all", lambda: None)
    monkeypatch.setattr("appaiforge.edge.write_portal_router", lambda: None)
    monkeypatch.setattr("appaiforge.ui.register_pages", lambda: None)
    monkeypatch.setattr("nicegui.ui.run_with", lambda *a, **kw: None)
    monkeypatch.delitem(sys.modules, "appaiforge.main", raising=False)

    importlib.import_module("appaiforge.main")
    monkeypatch.delitem(sys.modules, "appaiforge.main", raising=False)

    assert started == ["loop"]


# --- rota Docker idempotente (task 3.1) -------------------------------------------------------


def test_escrita_de_rota_igual_nao_reescreve_o_arquivo(tmp_path, monkeypatch):
    import os

    from appaiforge import edge
    from appaiforge.config import get_settings

    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        edge._write("apps-x.yml", edge.app_route_config("x"))
        path = tmp_path / "apps-x.yml"
        before = os.stat(path)
        edge._write("apps-x.yml", edge.app_route_config("x"))
        same = os.stat(path)
        assert (same.st_ino, same.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)

        edge._write("apps-x.yml", edge.app_route_config("y"))
        assert os.stat(path).st_ino != before.st_ino
        assert "apps/y" in path.read_text()
    finally:
        get_settings.cache_clear()
