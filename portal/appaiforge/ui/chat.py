"""Chat do editor com o agente do sistema (spec agent-harness).

Streaming: a página consulta (ui.timer) o buffer de eventos da run corrente e
anexa ao log — atualização em tempo real sem WebSocket manual (o canal do
NiceGUI já é WS). Interrupção chama queue.interrupt. A fila por sistema é
visível: run corrente + posição dos esperando.
"""

from nicegui import ui

from ..agent_queue import RunBuffer, get_queue
from ..models import AgentRun, RunStatus, System, User
from ..rbac import can_chat, can_manage_system

_EVENT_ICON = {
    "run_started": "▶",
    "message": "💬",
    "file_edited": "📝",
    "command_run": "⌨",
    "tool_output": "🔧",
    "usage": "📊",
    "run_finished": "✅",
    "gate_request": "🛑",
    "gate_denied": "⛔",
    "gate_approved": "✅",
    "gate_resolved": "⚖",
    "run_error": "❌",
    "run_interrupted": "⏹",
}


def render_chat(system: System, user: User) -> None:
    queue = get_queue()

    if not can_chat(user):
        ui.label("Somente editores conversam com o agente.").classes("text-gray-500")
        return

    log_box = ui.column().classes("w-full gap-1")
    state_label = ui.label("").classes("text-sm text-gray-500")
    input_row = ui.row().classes("w-full items-center")
    with input_row:
        prompt = ui.input(placeholder="Peça algo ao agente (ex.: crie um CRUD da tabela clientes)").classes("grow").props("data-testid=chat-input")
        send_btn = ui.button("Enviar").props("data-testid=chat-send")
        interrupt_btn = ui.button("Interromper").props("color=negative outline data-testid=chat-interrupt")
        interrupt_btn.set_visibility(False)

    current_run: dict = {"id": None, "shown": 0}
    pending_prompt: dict = {"text": None}
    approval_box = ui.column().classes("w-full")

    def do_send() -> None:
        text = (prompt.value or "").strip()
        if not text:
            return
        if current_run["id"] is not None:
            return  # agente ocupado: UI bloqueia; nada de corrida com a fila
        prompt.set_value("")
        pending_prompt["text"] = text
        refresh_state()

    def do_interrupt() -> None:
        if current_run["id"]:
            from ..services.systems import get_system

            fresh = get_system(system.id)
            queue.interrupt(current_run["id"], fresh)

    send_btn.on_click(do_send)
    interrupt_btn.on_click(do_interrupt)
    prompt.on("keydown.enter", do_send)

    approval_state: dict = {"request_id": None}

    def _render_approval() -> None:
        """Painel de aprovação do gate (spec destructive-gate): SQL + botões.

        Renderiza UMA vez por pedido — re-render a cada tick engole cliques.
        """
        run_id = current_run["id"]
        info = queue.pending_gates.get(run_id)
        if info is None:
            if approval_state["request_id"] is not None:
                approval_box.clear()
                approval_state["request_id"] = None
            return
        if approval_state["request_id"] == info["request_id"]:
            return  # painel já no ar para este pedido
        approval_state["request_id"] = info["request_id"]
        approval_box.clear()
        with approval_box:
            with ui.card().classes("w-full border-orange-400"):
                ui.label("🛑 O agente pede aprovação para uma operação destrutiva").classes("font-semibold text-orange-700")
                ui.label(f"SQL: {info['sql']}").classes("text-sm").style("white-space: pre-wrap")
                ui.label(f"motivo: {info['reason']}").classes("text-xs text-gray-600")

                def decide(approve: bool) -> None:
                    from ..models import User as UserM
                    from ..db import session_scope

                    with session_scope() as s:
                        author = s.get(UserM, user.id)
                        if author is not None:
                            s.expunge(author)
                    queue.decide_gate(run_id, info["request_id"], approve, author)

                with ui.row():
                    ui.button("Aprovar", on_click=lambda: decide(True)).props("color=negative data-testid=gate-approve")
                    ui.button("Recusar", on_click=lambda: decide(False)).props("outline data-testid=gate-deny")

    _QUIET_KINDS = {"tool_output", "usage"}  # detalhe técnico: fora do chat
                                             # (tokens ficam no painel "Uso de tokens")

    def render_event(box, event) -> None:
        if event.kind in _QUIET_KINDS:
            return

        icon = _EVENT_ICON.get(event.kind, "·")
        style = ""
        label = event.text or event.kind

        if event.kind == "command_run":
            label = f"comando: {(event.meta.get('command') or event.text or 'comando')[:160]}"
        elif event.kind == "file_edited":
            label = f"arquivo alterado: {event.text}"
        elif event.kind == "gate_request":
            with box:
                ui.label(f"🛑 PEDIDO DE APROVAÇÃO — comando de banco: {label}") \
                    .classes("text-sm text-orange-600 font-semibold") \
                    .style("white-space: pre-wrap")
            return
        elif event.kind == "gate_denied":
            style = "text-red-600 font-semibold"
        elif event.kind in ("gate_resolved", "gate_approved"):
            style = "text-green-700 font-semibold"

        with box:
            ui.label(f"{icon} {label}").classes(f"text-sm {style}").style("white-space: pre-wrap")

    def refresh_state() -> None:
        state = queue.system_state(system.id)
        position = state.get("queued", [])
        if state["running"]:
            if current_run["id"] != state["running"]:
                current_run["id"] = state["running"]
                current_run["shown"] = 0
                log_box.clear()
            buffer = queue.buffers.get(current_run["id"])
            if buffer:
                events = buffer.snapshot()
                for event in events[current_run["shown"]:]:
                    render_event(log_box, event)
                current_run["shown"] = len(events)
            interrupt_btn.set_visibility(True)
            state_label.set_text(
                "aguardando sua aprovação (gate de destrutivas)"
                if any(e.kind == "gate_request" for e in (queue.buffers.get(current_run["id"]) or RunBuffer()).snapshot())
                else "agente executando..."
            )
            _render_approval()
        else:
            # derrama o que faltou da run que acabou de terminar (o poll pode
            # ter perdido a janela "running" de runs curtas)
            if current_run["id"] is not None:
                buffer = queue.buffers.get(current_run["id"])
                if buffer:
                    events = buffer.snapshot()
                    for event in events[current_run["shown"]:]:
                        render_event(log_box, event)
                    current_run["shown"] = len(events)
            if position:
                state_label.set_text(f"{len(position)} pedido(s) na fila")
            else:
                state_label.set_text("agente livre")
            current_run["id"] = None
            interrupt_btn.set_visibility(False)
        if pending_prompt["text"] and state["running"] is None and not position:
            text = pending_prompt["text"]
            pending_prompt["text"] = None
            run = queue.enqueue(system.id, user.id, text)
            with log_box:
                ui.label(f"Você: {text}").classes("text-sm font-semibold")
            current_run["id"] = run.id
            current_run["shown"] = 0

    # runs anteriores (histórico persistido, sempre presente e vivo)
    with ui.expansion("Execuções anteriores", icon="history").classes("w-full") as history_exp:
        history_rows = ui.column().classes("w-full")

    def load_history() -> None:
        from ..db import session_scope
        from sqlalchemy import select

        with session_scope() as s:
            rows = s.execute(
                select(AgentRun).where(AgentRun.system_id == system.id, AgentRun.status != RunStatus.queued)
                .order_by(AgentRun.created_at.desc()).limit(10)
            ).scalars().all()
        fingerprint = tuple((r.id, r.status.value) for r in rows)
        if fingerprint == getattr(load_history, "_last", None):
            return
        load_history._last = fingerprint
        history_rows.clear()
        with history_rows:
            if not rows:
                ui.label("Nenhuma execução ainda.").classes("text-xs text-gray-400")
            for r in rows:
                status_label = {
                    RunStatus.succeeded: "concluída",
                    RunStatus.interrupted: "interrompida",
                    RunStatus.failed: "falhou",
                }.get(r.status, r.status.value)
                with ui.expansion(f"[{status_label}] {r.prompt[:60]} — {r.summary[:100] if r.summary else ''}").classes("w-full text-xs text-gray-500") as exp:
                    _load_run_events(r.id)

    def _load_run_events(run_id: str) -> None:
        """Carregar e renderizar eventos persistidos da run."""
        from ..db import session_scope
        from sqlalchemy import select
        from ..models import RunEventRecord

        with session_scope() as s:
            events = s.execute(
                select(RunEventRecord).where(RunEventRecord.run_id == run_id)
                .order_by(RunEventRecord.created_at)
            ).scalars().all()
        with ui.column().classes("w-full gap-1 pl-4"):
            for evt in events:
                if evt.kind in _QUIET_KINDS:
                    continue
                icon = _EVENT_ICON.get(evt.kind, "·")
                style = ""
                label = evt.text or evt.kind
                if evt.kind == "command_run":
                    label = f"comando: {(evt.meta.get('command') or evt.text or 'comando')[:160]}"
                elif evt.kind == "file_edited":
                    label = f"arquivo alterado: {evt.text}"
                elif evt.kind == "gate_denied":
                    style = "text-red-600 font-semibold"
                elif evt.kind in ("gate_resolved", "gate_approved"):
                    style = "text-green-700 font-semibold"
                ui.label(f"{icon} {label}").classes(f"text-sm {style}").style("white-space: pre-wrap")

    load_history()
    ui.timer(2.0, load_history)
    ui.timer(0.5, refresh_state)
