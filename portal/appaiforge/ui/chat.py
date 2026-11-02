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

# marcadores de transição de execução: ficam fora das bolhas de chat
_STATUS_ICON = {
    "run_started": ("play_arrow", "text-gray-400"),
    "run_finished": ("check_circle", "text-green-600"),
    "run_interrupted": ("stop_circle", "text-gray-500"),
    "run_error": ("error", "text-red-600"),
}

# ícone exibido ao lado da bolha, conforme o tipo de evento
_EVENT_ICON = {
    "file_edited": "description",
    "command_run": "terminal",
    "gate_request": "warning",
    "gate_denied": "block",
    "gate_approved": "check_circle",
    "gate_resolved": "gavel",
}

_GATE_COLOR_PROPS = {
    "gate_request": "bg-color=orange-2 text-color=orange-10",
    "gate_denied": "bg-color=red-2 text-color=red-10",
    "gate_approved": "bg-color=green-2 text-color=green-10",
    "gate_resolved": "bg-color=green-2 text-color=green-10",
}

_QUIET_KINDS = {"tool_output", "usage"}  # detalhe técnico: fora do chat
                                         # (tokens ficam no painel "Uso de tokens")


def render_chat(system: System, user: User) -> None:
    queue = get_queue()

    if not can_chat(user):
        ui.label("Somente editores conversam com o agente.").classes("text-gray-500")
        return

    with ui.scroll_area().classes("w-full h-96 border rounded"):
        log_box = ui.column().classes("w-full gap-1 p-2")
        approval_box = ui.column().classes("w-full")
    state_label = ui.label("").classes("text-sm text-gray-500")
    input_row = ui.row().classes("w-full items-center")
    with input_row:
        prompt = ui.input(placeholder="Peça algo ao agente (ex.: crie um CRUD da tabela clientes)").classes("grow").props("data-testid=chat-input")
        send_btn = ui.button("Enviar", icon="send").props("data-testid=chat-send")
        interrupt_btn = ui.button("Interromper", icon="stop").props("color=negative outline data-testid=chat-interrupt")
        interrupt_btn.set_visibility(False)

    current_run: dict = {"id": None, "shown": 0}
    pending_prompt: dict = {"text": None}

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
                ui.label("O agente pede aprovação para uma operação destrutiva").classes("font-semibold text-orange-700")
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
                    ui.button("Aprovar", icon="check", on_click=lambda: decide(True)).props("color=negative data-testid=gate-approve")
                    ui.button("Recusar", icon="close", on_click=lambda: decide(False)).props("outline data-testid=gate-deny")

    def render_event(box, event) -> None:
        """Renderiza um evento (RunEvent em memória ou RunEventRecord persistido)
        como bolha de chat ou marcador de status compacto."""
        if event.kind in _QUIET_KINDS:
            return

        if event.kind in _STATUS_ICON:
            icon, color = _STATUS_ICON[event.kind]
            with box, ui.row().classes("w-full justify-center items-center gap-1"):
                ui.icon(icon).classes(f"text-sm {color}")
                ui.label(event.kind).classes(f"text-xs {color}")
            return

        if event.kind == "gate_request":
            command = event.meta.get("command") or event.text or "comando"
            text = f"PEDIDO DE APROVAÇÃO — comando de banco: {command}"
        elif event.kind == "command_run":
            text = f"comando: {(event.meta.get('command') or event.text or 'comando')[:160]}"
        elif event.kind == "file_edited":
            text = f"arquivo alterado: {event.text}"
        else:
            text = event.text or event.kind

        with box:
            with ui.row().classes("w-full items-center gap-1"):
                icon = _EVENT_ICON.get(event.kind)
                if icon:
                    ui.icon(icon).classes("text-gray-500")
                msg = ui.chat_message(text=text, name="Agente", sent=False)
                color_props = _GATE_COLOR_PROPS.get(event.kind)
                if color_props:
                    msg.props(color_props)

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
            # current_run precisa ser atualizado ANTES de criar a bolha: criar
            # ui.chat_message cede ao event loop o suficiente para o ui.timer
            # de 0.5s dar refresh_state() concorrente nesse meio-tempo — se
            # ele visse current_run["id"] ainda None aqui, achava que é uma
            # run "nova" vinda de fora e limpava o log_box, apagando a bolha.
            current_run["id"] = run.id
            current_run["shown"] = 0
            with log_box:
                ui.chat_message(text=text, name="Você", sent=True)

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
        """Carregar e renderizar eventos persistidos da run (mesmo mapeamento do log ao vivo)."""
        from ..db import session_scope
        from sqlalchemy import select
        from ..models import RunEventRecord

        with session_scope() as s:
            events = s.execute(
                select(RunEventRecord).where(RunEventRecord.run_id == run_id)
                .order_by(RunEventRecord.created_at)
            ).scalars().all()
        box = ui.column().classes("w-full gap-1 pl-4")
        for evt in events:
            render_event(box, evt)

    load_history()
    ui.timer(2.0, load_history)
    ui.timer(0.5, refresh_state)
