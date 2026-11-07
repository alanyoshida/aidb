"""Unitários da comparação do spike S5 (task 6.2): dado real sintético —
inserido direto como GateDecision, sem passar pelo proxy nem pelo harness —
exercitando o casamento run_id+janela de tempo e as quatro categorias."""

from datetime import timedelta

import pytest

from appaiforge import auth, gate_comparison
from appaiforge.db import session_scope
from appaiforge.models import AgentRun, GateDecision, RunStatus, UserType, utcnow
from appaiforge.services.systems import create_system


@pytest.fixture()
def cmp_system(clean_db):
    editor = auth.create_user("cmp@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Cmp", "cmp-svc")


@pytest.fixture()
def run_id(cmp_system):
    editor = auth.create_user("cmp-run@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run = AgentRun(
            system_id=cmp_system.id, user_id=editor.id, user_email=editor.email,
            status=RunStatus.running, prompt="p",
        )
        s.add(run)
        s.flush()
        return run.id


def _insert(system_id, run_id, sql, classification, decision, *, connection_name="", offset_seconds=0):
    with session_scope() as s:
        s.add(GateDecision(
            system_id=system_id, run_id=run_id, origin="agente", sql=sql,
            connection_name=connection_name, classification=classification, decision=decision,
            created_at=utcnow() + timedelta(seconds=offset_seconds),
        ))


def test_concordancia_quando_classificacao_bate(cmp_system, run_id):
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "aprovada", offset_seconds=0)
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=1)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert report.concordancia_count == 1
    assert report.escapes == []
    assert report.sem_correspondencia_antiga == []
    assert report.discordancia == []


def test_escape_quando_sombra_sem_correspondencia_antiga(cmp_system, run_id):
    """O caso central da etapa 4: o glob nunca perguntou, mas o proxy viu."""
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=0)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert len(report.escapes) == 1
    assert report.escapes[0]["sql"] == "DELETE FROM t"
    assert report.concordancia_count == 0


def test_normal_sem_correspondencia_nao_conta_como_escape(cmp_system, run_id):
    """SELECT/normal não gera atrito nenhum — não é interessante reportar
    como "escape" mesmo sem par (ver _FRICTION_CLASSES)."""
    _insert(cmp_system.id, run_id, "SELECT 1", "normal", "sombra", offset_seconds=0)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert report.escapes == []


def test_sem_correspondencia_antiga_quando_glob_perguntou_sem_par_em_sombra(cmp_system, run_id):
    _insert(cmp_system.id, run_id, "DROP TABLE t", "bloqueada", "bloqueada", offset_seconds=0)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert len(report.sem_correspondencia_antiga) == 1
    assert report.sem_correspondencia_antiga[0]["decision"] == "bloqueada"


def test_discordancia_quando_classificacao_diverge_entre_os_dois_caminhos(cmp_system, run_id):
    """extract_sql (regex) pegou um texto diferente do que foi pro banco —
    sinal de que a extração do caminho antigo é imprecisa."""
    _insert(cmp_system.id, run_id, "DELETE FROM t WHERE id = 1", "normal", "aprovada", offset_seconds=0)
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=1)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert len(report.discordancia) == 1
    assert report.discordancia[0]["antigo"]["classification"] == "normal"
    assert report.discordancia[0]["sombra"]["classification"] == "confirmavel"
    assert report.concordancia_count == 0


def test_casamento_respeita_janela_de_tempo(cmp_system, run_id):
    """Fora da janela, os dois ficam sem par — não casa coisas distantes no
    tempo só porque sobrou um de cada lado."""
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "aprovada", offset_seconds=0)
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=120)

    report = gate_comparison.compare(system_id=cmp_system.id, window_seconds=30.0)
    assert report.concordancia_count == 0
    assert len(report.escapes) == 1
    assert len(report.sem_correspondencia_antiga) == 1


def test_casamento_guloso_prefere_o_par_mais_proximo(cmp_system, run_id):
    """Dois candidatos do lado antigo pro mesmo evento em sombra: casa com
    o mais próximo no tempo, não com o primeiro que aparecer."""
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "aprovada", offset_seconds=0)
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "aprovada", offset_seconds=10)
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=9)

    report = gate_comparison.compare(system_id=cmp_system.id, window_seconds=30.0)
    assert report.concordancia_count == 1
    assert len(report.sem_correspondencia_antiga) == 1  # o par de offset=0 fica sem casar


def test_runs_diferentes_nunca_casam_entre_si(cmp_system):
    """Mesmo perto no tempo, eventos de runs diferentes não se casam — cada
    run é isolado (duas execuções concorrentes não deveriam se confundir)."""
    editor = auth.create_user("cmp-run2@t.local", "pw", UserType.editor.value)
    with session_scope() as s:
        run_a = AgentRun(system_id=cmp_system.id, user_id=editor.id, user_email=editor.email,
                         status=RunStatus.running, prompt="a")
        run_b = AgentRun(system_id=cmp_system.id, user_id=editor.id, user_email=editor.email,
                         status=RunStatus.running, prompt="b")
        s.add_all([run_a, run_b])
        s.flush()
        run_a_id, run_b_id = run_a.id, run_b.id

    _insert(cmp_system.id, run_a_id, "DELETE FROM t", "confirmavel", "aprovada", offset_seconds=0)
    _insert(cmp_system.id, run_b_id, "DELETE FROM t", "confirmavel", "sombra", offset_seconds=1)

    report = gate_comparison.compare(system_id=cmp_system.id)
    assert report.concordancia_count == 0
    assert len(report.escapes) == 1
    assert len(report.sem_correspondencia_antiga) == 1


def test_since_days_filtra_decisoes_antigas(cmp_system, run_id):
    _insert(cmp_system.id, run_id, "DELETE FROM t", "confirmavel", "sombra",
           offset_seconds=-int(timedelta(days=90).total_seconds()))

    report = gate_comparison.compare(system_id=cmp_system.id, since_days=30)
    assert report.total_sombra == 0
    assert report.escapes == []


def test_format_report_nao_levanta_com_relatorio_vazio(cmp_system):
    report = gate_comparison.compare(system_id=cmp_system.id)
    text = gate_comparison.format_report(report)
    assert "Comparação S5" in text
