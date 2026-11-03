"""Unitários: FakeHarness, fila por sistema (ordem/interrupção), checkpoints git,
guidelines e materialização (tasks 5.2, 5.3, 5.6, 5.7)."""

import os
import time

import pytest

from appaiforge import auth
from appaiforge.agent_queue import AgentQueue, RunBuffer
from appaiforge.checkpoints import commit_all, list_checkpoints, record_checkpoint, rollback
from appaiforge.guidelines import current_content, materialize, update_content
from appaiforge.harness.base import RunEvent
from appaiforge.harness.fake import FakeHarness
from appaiforge.models import RunStatus, SystemStatus, UserType
from appaiforge.services.systems import create_system


@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_fake_harness_emite_sequencia_completa(fake_workspace):
    harness = FakeHarness(str(fake_workspace / "workspaces"), step_delay=0)
    events: list[RunEvent] = []
    harness.run({"slug": "erp"}, "ses_1", "crie um CRUD", events.append)
    kinds = [e.kind for e in events]
    assert kinds[0] == "run_started"
    assert "file_edited" in kinds and "command_run" in kinds and "usage" in kinds
    assert kinds[-1] == "run_finished"
    assert (fake_workspace / "workspaces" / "erp" / "app" / "main.py").is_file()


def test_buffer_de_eventos_thread_safe():
    buf = RunBuffer()
    for i in range(10):
        buf.push(RunEvent("message", text=str(i)))
    assert len(buf.snapshot()) == 10


def test_fila_executa_dois_pedidos_em_serie_na_ordem(clean_db, fake_workspace):
    editor = auth.create_user("queue@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Fila", "fila")

    class SlowFake(FakeHarness):
        def run(self, system, session_id, prompt, on_event):
            on_event(RunEvent("run_started"))
            time.sleep(0.3)
            on_event(RunEvent("message", text=prompt))
            on_event(RunEvent("run_finished", meta={"summary": prompt}))

    queue = AgentQueue(SlowFake(str(fake_workspace), step_delay=0))
    r1 = queue.enqueue(system.id, editor.id, "pedido-1")
    r2 = queue.enqueue(system.id, editor.id, "pedido-2")

    deadline = time.time() + 10
    while time.time() < deadline:
        with open("/dev/null"):
            pass
        from appaiforge.db import session_scope
        from sqlalchemy import select
        from appaiforge.models import AgentRun

        with session_scope() as s:
            rows = s.execute(select(AgentRun.status).where(AgentRun.id.in_([r1.id, r2.id]))).all()
        if all(st == RunStatus.succeeded for (st,) in rows):
            break
        time.sleep(0.1)

    from appaiforge.db import session_scope
    from sqlalchemy import select
    from appaiforge.models import AgentRun

    with session_scope() as s:
        summaries = s.execute(
            select(AgentRun.summary).where(AgentRun.id.in_([r1.id, r2.id])).order_by(AgentRun.created_at)
        ).scalars().all()
    assert summaries == ["pedido-1", "pedido-2"]


def test_checkpoints_commit_e_rollback(fake_workspace):
    from appaiforge.config import get_settings
    from pathlib import Path

    editor = None  # commit sem autor usa fallback
    system = type("S", (), {"slug": "ckpt", "id": "sys1", "owner_id": "u1"})()

    ws = Path(get_settings().workspaces_dir) / "ckpt"
    ws.mkdir(parents=True)
    (ws / "app").mkdir()
    (ws / "app" / "main.py").write_text("v1\n")

    sha1 = commit_all(system, "primeira versão", author=None)
    assert sha1
    (ws / "app" / "main.py").write_text("v2\n")
    (ws / "extra.txt").write_text("novo\n")
    sha2 = commit_all(system, "segunda versão", author=None)
    assert sha2 != sha1

    rollback(system, sha1)
    assert (ws / "app" / "main.py").read_text() == "v1\n"
    assert not (ws / "extra.txt").exists()


def test_record_checkpoint_registra_historico(fake_workspace, clean_db):
    from appaiforge.config import get_settings
    from pathlib import Path

    editor = auth.create_user("ckpt@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Ckpt", "ckpt-hist")
    ws = Path(get_settings().workspaces_dir) / system.slug
    (ws / "app").mkdir(parents=True, exist_ok=True)
    (ws / "app" / "main.py").write_text("v1\n")

    cp = record_checkpoint(system, None, "geração inicial", editor)
    assert cp is not None and len(cp.git_sha) == 40
    history = list_checkpoints(system)
    assert len(history) == 1 and history[0]["message"] == "geração inicial"
    # nada mudou desde o último commit -> sem checkpoint novo
    assert record_checkpoint(system, None, "nada mudou", editor) is None


def test_guidelines_atualizacao_propaga_para_workspace(fake_workspace, clean_db):
    admin = auth.create_user("gadmin@t.local", "pw", UserType.admin.value)
    editor = auth.create_user("ged@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Guides", "guides")

    before = materialize(system)
    assert "AIDB" in open(before).read()

    update_content("Regra nova: use sempre PT-BR nos rótulos.", admin.id)
    after = materialize(system)
    content = open(after).read()
    assert "Regra nova" in content
    assert current_content().startswith("Regra nova")


def test_run_sem_resposta_do_provedor_falha_com_mensagem(fake_workspace, clean_db):
    """Provider aceito mas sem nenhum evento do assistente -> falha clara (caso 1113)."""
    from appaiforge.db import session_scope
    from sqlalchemy import select
    from appaiforge.models import AgentRun

    class SilentHarness(FakeHarness):
        def run(self, system, session_id, prompt, on_event):
            on_event(RunEvent("run_started"))
            on_event(RunEvent("run_finished", meta={"summary": ""}))  # idle imediato, sem trabalho

    editor = auth.create_user("silent@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Silent", "silent-run")
    queue = AgentQueue(SilentHarness(str(fake_workspace / "workspaces"), step_delay=0))
    run = queue.enqueue(system.id, editor.id, "qualquer coisa")

    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        with session_scope() as s:
            row = s.get(AgentRun, run.id)
            if row.status in (RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted):
                break
        time.sleep(0.1)
    with session_scope() as s:
        row = s.get(AgentRun, run.id)
        assert row.status == RunStatus.failed
        assert "não retornou resposta" in row.summary


def test_templates_materializados_iguais_ao_original(fake_workspace, clean_db):
    """Task 1.3: as cópias em portal_templates/ são byte a byte com app_template/."""
    import os

    from appaiforge.guidelines import TEMPLATES_PACKAGE_DIR, TEMPLATE_FILES, materialize

    editor = auth.create_user("tmpl@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Tmpl", "tmpl-mat")
    materialize(system)

    templates_dir = os.path.join(fake_workspace / "workspaces", system.slug, "portal_templates")
    for name in TEMPLATE_FILES:
        with open(os.path.join(templates_dir, name), "rb") as copy, \
             open(os.path.join(TEMPLATES_PACKAGE_DIR, name), "rb") as original:
            assert copy.read() == original.read(), f"{name} divergiu do original"


def test_guidelines_exigem_camada_dbgate(fake_workspace, clean_db):
    from appaiforge.guidelines import current_content

    content = current_content()
    assert "dbgate" in content and "GateConfirmationRequired" in content and "uv add sqlglot" in content


def test_eventos_sao_redigidos_antes_do_buffer(fake_workspace, clean_db):
    """Spec db-connections: segredos nunca aparecem em eventos do agente."""
    from appaiforge.agent_queue import RunBuffer
    from appaiforge.harness.base import RunEvent as RE

    class LeakyFake(FakeHarness):
        def run(self, system, session_id, prompt, on_event):
            on_event(RE("run_started"))
            on_event(RE("tool_output", text="DATABASE_URL_VENDAS=postgresql://appaiforge:senhona@db:5432/homolog"))
            on_event(RE("command_run", text="psql postgresql://appaiforge:senhona@db:5432/homolog -c 'SELECT 1'",
                        meta={"command": "psql postgresql://appaiforge:senhona@db:5432/homolog -c 'SELECT 1'"}))
            on_event(RE("run_finished", meta={"summary": "ok"}))

    editor = auth.create_user("redact@t.local", "pw", UserType.editor.value)
    system = create_system(editor, "Redact", "redact-run")
    queue = AgentQueue(LeakyFake(str(fake_workspace / "workspaces"), step_delay=0))
    run = queue.enqueue(system.id, editor.id, "mostra o env")

    import time
    from appaiforge.db import session_scope
    from sqlalchemy import select
    from appaiforge.models import AgentRun

    deadline = time.time() + 10
    while time.time() < deadline:
        with session_scope() as s:
            row = s.get(AgentRun, run.id)
            if row is not None and row.status in (RunStatus.succeeded, RunStatus.failed):
                break
        time.sleep(0.1)

    events_text = "\n".join(e.text + (e.meta.get("command") or "") for e in queue.buffers[run.id].snapshot())
    assert "senhona" not in events_text
    assert ":***@" in events_text
