"""Testes do shim HTTP do perfil claude-code (change add-claude-code-agent-profile).

Task 2.1: duas invocações na mesma sessão lógica -> só a segunda leva --resume.
Task 2.2: tradução de linha stdout -> envelope SSE, sem subprocess real (fixture).
Task 2.3: env de telemetria desligada chega no subprocesso.
"""

import json
import queue

import pytest

import shim


def test_build_claude_args_sem_resume_na_primeira_vez():
    args = shim.build_claude_args("oi", model=None, resume_cli_session_id=None)
    assert "--resume" not in args
    assert args[:3] == ["claude", "-p", "oi"]
    assert "--verbose" in args
    assert "--settings" in args


def test_build_claude_args_com_resume_quando_ja_tem_sessao():
    args = shim.build_claude_args("de novo", model=None, resume_cli_session_id="cli-sid-123")
    i = args.index("--resume")
    assert args[i + 1] == "cli-sid-123"


def test_build_claude_args_passa_model_quando_informado():
    args = shim.build_claude_args("oi", model="claude-opus-5-5", resume_cli_session_id=None)
    i = args.index("--model")
    assert args[i + 1] == "claude-opus-5-5"


def test_build_claude_args_sem_mcp_config_quando_sistema_nao_tem_conexao():
    args = shim.build_claude_args("oi", model=None, resume_cli_session_id=None, mcp_config_path=None)
    assert "--mcp-config" not in args
    assert "--strict-mcp-config" not in args


def test_build_claude_args_com_mcp_config_quando_informado():
    args = shim.build_claude_args("oi", model=None, resume_cli_session_id=None, mcp_config_path="/claude-code-config/mcp-servers.json")
    i = args.index("--mcp-config")
    assert args[i + 1] == "/claude-code-config/mcp-servers.json"
    assert "--strict-mcp-config" in args


def test_build_claude_env_desliga_telemetria_preservando_base():
    base = {"ANTHROPIC_API_KEY": "sys1.abc", "PATH": "/usr/bin"}
    env = shim.build_claude_env(base)
    assert env["ANTHROPIC_API_KEY"] == "sys1.abc"
    assert env["PATH"] == "/usr/bin"
    for key, value in shim._TELEMETRY_OFF_ENV.items():
        assert env[key] == value


def test_parse_event_line_ignora_linha_vazia_e_invalida():
    assert shim.parse_event_line("") is None
    assert shim.parse_event_line("   ") is None
    assert shim.parse_event_line("not json") is None
    assert shim.parse_event_line("[1, 2]") is None  # lista, não objeto


def test_parse_event_line_shape_real_do_spike():
    raw = '{"type":"result","subtype":"success","session_id":"cli-abc","is_error":false}'
    event = shim.parse_event_line(raw)
    assert event == {"type": "result", "subtype": "success", "session_id": "cli-abc", "is_error": False}


def test_translate_event_reescreve_session_id_pro_id_logico():
    original = {"type": "assistant", "session_id": "cli-abc", "message": {"content": []}}
    translated = shim.translate_event(original, "logico-123")
    assert translated["session_id"] == "logico-123"
    assert translated["type"] == "assistant"
    # não muta o dict original
    assert original["session_id"] == "cli-abc"


class FakeProc:
    """Substitui subprocess.Popen nos testes de run_prompt — sem CLI real."""

    def __init__(self, stdout_lines: list[str], cli_session_id: str):
        self.stdout = iter(stdout_lines)
        self.stderr = iter([])
        self._waited = False
        self.sent_signals: list[int] = []
        self.cli_session_id = cli_session_id

    def wait(self):
        self._waited = True

    def send_signal(self, sig):
        self.sent_signals.append(sig)


def _init_and_result_lines(cli_session_id: str) -> list[str]:
    init = json.dumps({"type": "system", "subtype": "init", "session_id": cli_session_id})
    result = json.dumps({"type": "result", "subtype": "success", "session_id": cli_session_id, "is_error": False})
    return [init + "\n", result + "\n"]


def test_run_prompt_so_passa_mcp_config_quando_arquivo_existe(monkeypatch):
    import shutil
    import tempfile

    work_dir = tempfile.mkdtemp(prefix="claude-code-shim-test-")
    try:
        state = shim.ShimState()
        session_id = state.create_session()
        session = state.get_session(session_id)
        spawned_args: list[list[str]] = []

        def fake_popen(args, **kwargs):
            spawned_args.append(args)
            return FakeProc(_init_and_result_lines("cli-sid-mcp"), "cli-sid-mcp")

        monkeypatch.setattr(shim.subprocess, "Popen", fake_popen)

        missing_path = f"{work_dir}/nao-existe.json"
        monkeypatch.setattr(shim, "MCP_CONFIG_PATH", missing_path)
        shim.run_prompt(state, session_id, session, "oi", None)
        assert "--mcp-config" not in spawned_args[0]

        existing_path = f"{work_dir}/mcp-servers.json"
        with open(existing_path, "w") as f:
            f.write("{}")
        monkeypatch.setattr(shim, "MCP_CONFIG_PATH", existing_path)
        shim.run_prompt(state, session_id, session, "de novo", None)
        assert "--mcp-config" in spawned_args[1]
        i = spawned_args[1].index("--mcp-config")
        assert spawned_args[1][i + 1] == existing_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_run_prompt_duas_chamadas_mesma_sessao_logica_so_a_segunda_tem_resume(monkeypatch):
    state = shim.ShimState()
    session_id = state.create_session()
    session = state.get_session(session_id)

    spawned_args: list[list[str]] = []
    cli_sid = "cli-session-xyz"

    def fake_popen(args, **kwargs):
        spawned_args.append(args)
        return FakeProc(_init_and_result_lines(cli_sid), cli_sid)

    monkeypatch.setattr(shim.subprocess, "Popen", fake_popen)

    shim.run_prompt(state, session_id, session, "primeira", None)
    shim.run_prompt(state, session_id, session, "segunda", None)

    assert len(spawned_args) == 2
    assert "--resume" not in spawned_args[0]
    assert "--resume" in spawned_args[1]
    i = spawned_args[1].index("--resume")
    assert spawned_args[1][i + 1] == cli_sid


def test_run_prompt_publica_eventos_com_session_id_logico(monkeypatch):
    state = shim.ShimState()
    session_id = state.create_session()
    session = state.get_session(session_id)
    q = state.bus.subscribe()

    def fake_popen(args, **kwargs):
        return FakeProc(_init_and_result_lines("cli-sid-1"), "cli-sid-1")

    monkeypatch.setattr(shim.subprocess, "Popen", fake_popen)
    shim.run_prompt(state, session_id, session, "oi", None)

    seen = []
    while True:
        try:
            seen.append(q.get_nowait())
        except queue.Empty:
            break

    assert len(seen) == 2
    assert all(e["session_id"] == session_id for e in seen)
    assert seen[0]["type"] == "system"
    assert seen[-1]["type"] == "result"


def test_run_prompt_sintetiza_result_quando_cli_morre_sem_emitir_um(monkeypatch):
    """Simula /abort: subprocesso termina sem nunca emitir um evento "result"
    (ex.: matado no meio) — o shim precisa fechar o turno mesmo assim, senão
    o harness.run() do portal fica esperando pra sempre."""
    state = shim.ShimState()
    session_id = state.create_session()
    session = state.get_session(session_id)
    q = state.bus.subscribe()

    only_init = [json.dumps({"type": "system", "subtype": "init", "session_id": "cli-sid-2"}) + "\n"]

    def fake_popen(args, **kwargs):
        return FakeProc(only_init, "cli-sid-2")

    monkeypatch.setattr(shim.subprocess, "Popen", fake_popen)
    session.abort_requested = True
    shim.run_prompt(state, session_id, session, "oi", None)

    seen = []
    while True:
        try:
            seen.append(q.get_nowait())
        except queue.Empty:
            break

    assert seen[-1]["type"] == "result"
    assert seen[-1]["subtype"] == "aborted"
    assert seen[-1]["is_error"] is True
    assert seen[-1]["session_id"] == session_id
    # abort_requested é consumido (não vaza pro próximo turno)
    assert session.abort_requested is False
