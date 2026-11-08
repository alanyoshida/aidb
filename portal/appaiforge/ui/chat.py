"""Chat do editor com o agente do sistema (spec agent-harness).

Streaming: a página consulta (ui.timer) o buffer de eventos da run corrente e
anexa ao log — atualização em tempo real sem WebSocket manual (o canal do
NiceGUI já é WS). Interrupção chama queue.interrupt. A fila por sistema é
visível: run corrente + posição dos esperando.
"""

import base64
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nicegui import ui

from ..agent_queue import get_queue
from ..config import get_settings
from ..models import AgentRun, ChatSession, RunStatus, System, User
from ..rbac import can_chat, can_manage_system
from . import theme as _theme

def _stamp(dt: datetime | None) -> str:
    """Formata um horário UTC no fuso de exibição, como "dd/mm HH:MM"."""
    if dt is None:
        return ""
    if dt.tzinfo is None:  # driver pode devolver naive; o banco grava em UTC
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        local = dt.astimezone(ZoneInfo(get_settings().display_timezone))
    except ZoneInfoNotFoundError:
        local = dt
    return local.strftime("%d/%m %H:%M")


def _sender_label(name: str, dt: datetime | None) -> str:
    """Nome com o horário ao lado.

    Vai no `name` em vez do `stamp` do Quasar porque o stamp renderiza dentro
    da bolha; a linha do nome fica fora dela.
    """
    stamp = _stamp(dt)
    return f"{name} · {stamp}" if stamp else name


def _avatars(user: User) -> tuple[str, str]:
    """(avatar do usuário, avatar do agente) nas cores do tema escolhido."""
    t = _theme.tokens(*_theme.parse_key(user.theme))
    return (
        _theme.avatar_svg(t["--ch-user-bg"], t["--ch-user-txt"], "VC"),
        _theme.avatar_svg(t["--ch-avatar-bg"], t["--ch-avatar-txt"], "AI"),
    )

_ARTIFACT_PATTERN = re.compile(
    r"```(echart|table|html)\n(.*?)```",
    re.DOTALL,
)


def parse_artifacts(text: str) -> list[tuple[str, str]]:
    """Divide o texto em segmentos de texto puro e blocos de artifact.

    Retorna lista de (kind, conteúdo) onde kind é "text", "echart", "table" ou "html".
    """
    segments: list[tuple[str, str]] = []
    last = 0
    for m in _ARTIFACT_PATTERN.finditer(text):
        before = text[last : m.start()]
        if before:
            segments.append(("text", before))
        segments.append((m.group(1), m.group(2).strip()))
        last = m.end()
    tail = text[last:]
    if tail:
        segments.append(("text", tail))
    return segments if segments else [("text", text)]


def render_artifact_segment(box, kind: str, raw: str) -> None:
    """Renderiza um segmento: texto como markdown, artifacts como componentes visuais."""
    with box:
        if kind == "text":
            if raw.strip():
                ui.markdown(raw)

        elif kind == "echart":
            try:
                config = json.loads(raw)
                if not isinstance(config, dict):
                    raise ValueError("configuração ECharts deve ser um objeto JSON")
                ui.echart(config).classes("w-full h-64")
            except Exception as exc:
                _render_artifact_error(box, "echart", str(exc), raw)

        elif kind == "table":
            try:
                rows = json.loads(raw)
                if not isinstance(rows, list):
                    raise ValueError("dados de tabela devem ser um array JSON")
                if rows:
                    columns = [
                        {"field": k, "filter": True, "sortable": True}
                        for k in rows[0].keys()
                    ]
                else:
                    columns = []
                ui.aggrid({"columnDefs": columns, "rowData": rows}).classes("w-full h-48")
            except Exception as exc:
                _render_artifact_error(box, "table", str(exc), raw)

        elif kind == "html":
            if raw.strip():
                encoded = base64.b64encode(raw.encode()).decode()
                ui.element("iframe").props(
                    f'src="data:text/html;base64,{encoded}" '
                    f'sandbox="allow-same-origin"'
                ).style("width:100%;min-height:200px;border:none;resize:vertical;overflow:auto;")


def _render_artifact_error(box, kind: str, err: str, raw: str) -> None:
    with box, ui.card().classes("w-full border border-red-300 bg-red-50 p-2"):
        ui.label(f"Artifact inválido ({kind}): {err}").classes("text-xs text-red-700 font-medium")
        with ui.expansion("Ver conteúdo bruto").classes("text-xs text-red-500"):
            ui.code(raw, language="text").classes("text-xs")

# marcadores de transição de execução: ficam fora das bolhas de chat
# (ícone, cor, rótulo exibido)
_STATUS_ICON = {
    "run_started": ("play_arrow", "text-gray-400", "execução iniciada"),
    "run_finished": ("check_circle", "text-green-600", "execução concluída"),
    "run_interrupted": ("stop_circle", "text-gray-500", "execução interrompida"),
    "run_error": ("error", "text-red-600", "erro na execução"),
    "session_context_reset": ("refresh", "text-amber-600", "contexto reiniciado"),
}

# ícone exibido ao lado da bolha, conforme o tipo de evento
_EVENT_ICON = {
    "file_edited": "description",
    "command_run": "terminal",
    "gate_request": "warning",
    "gate_denied": "block",
    "gate_approved": "check_circle",
    "gate_resolved": "gavel",
    "question_asked": "help",
    "question_resolved": "gavel",
}

_GATE_COLOR_PROPS = {
    "gate_request": "bg-color=orange-2 text-color=orange-10",
    "gate_denied": "bg-color=red-2 text-color=red-10",
    "gate_approved": "bg-color=green-2 text-color=green-10",
    "gate_resolved": "bg-color=green-2 text-color=green-10",
    "question_asked": "bg-color=blue-2 text-color=blue-10",
    "question_resolved": "bg-color=green-2 text-color=green-10",
}

_QUIET_KINDS = {"tool_output", "usage"}  # detalhe técnico: fora do chat
                                         # (tokens ficam no painel "Uso de tokens")

# Detalhe técnico da execução: fica no DOM mas oculto enquanto o debug está
# desligado; alternar o switch é instantâneo (não precisa re-renderizar).
_DEBUG_KINDS = {"command_run", "file_edited"}
_DEBUG_CSS = ".af-hide-debug .af-debug { display: none !important; }"


def render_chat(system: System, user: User) -> None:
    queue = get_queue()
    ui.add_css(_DEBUG_CSS)
    _AVATAR_USER, _AVATAR_AGENT = _avatars(user)

    if not can_chat(user):
        ui.label("Somente editores conversam com o agente.").classes("text-gray-500")
        return

    # --- painel de sessões ---------------------------------------------------
    active_session: dict = {"id": None}  # ChatSession.id da sessão ativa
    rename_state: dict = {"editing": False}

    with ui.expansion("Sessões", icon="chat").classes("w-full"):
        sessions_col = ui.column().classes("w-full gap-1")
        ui.button("Nova sessão", icon="add", on_click=lambda: _new_session()).props(
            "flat dense data-testid=chat-new-session"
        ).classes("text-xs")

    session_title_row = ui.row().classes("w-full items-center gap-1")
    with session_title_row:
        session_title_label = ui.label("").classes("text-sm font-medium text-gray-700 grow")
        rename_btn = ui.button(icon="edit", on_click=lambda: _start_rename()).props("flat dense round")
    rename_row = ui.row().classes("w-full items-center gap-1")
    rename_row.set_visibility(False)
    with rename_row:
        rename_input = ui.input("Novo título").classes("grow")
        ui.button("OK", on_click=lambda: _confirm_rename()).props("flat dense")
        ui.button("×", on_click=lambda: rename_row.set_visibility(False)).props("flat dense")

    # --- log do chat ---------------------------------------------------------
    with ui.scroll_area().classes("w-full h-96 border rounded af-chat-scroll"):
        log_box = ui.column().classes("w-full gap-1 p-2 af-hide-debug")
        approval_box = ui.column().classes("w-full")
    with ui.row().classes("w-full items-center justify-center gap-2"):
        state_dot = ui.element("span").classes("ap-dot")
        state_label = ui.label("").classes("text-sm text-gray-500")

    def set_state(text: str, busy: bool) -> None:
        state_label.set_text(text)
        if busy:
            state_dot.classes(add="ap-dot--busy")
        else:
            state_dot.classes(remove="ap-dot--busy")
    debug = {"on": False}
    debug_switch = ui.switch("Debug (mostrar comandos e arquivos alterados)").props("data-testid=chat-debug")
    input_row = ui.row().classes("w-full items-center")
    with input_row:
        prompt = ui.input(placeholder="Peça algo ao agente (ex.: crie um CRUD da tabela clientes)").classes("grow af-chat-input").props("data-testid=chat-input borderless")
        send_btn = ui.button(icon="send").classes("af-chat-send").props("flat round data-testid=chat-send")
        interrupt_btn = ui.button(icon="stop").props(
            'color=negative flat round data-testid=chat-interrupt aria-label="Interromper"'
        ).tooltip("Interromper")
        interrupt_btn.set_visibility(False)

    current_run: dict = {"id": None, "shown": 0}
    pending_prompt: dict = {"text": None}

    # -------------------------------------------------------------------------
    # Helpers de sessão
    # -------------------------------------------------------------------------

    def _load_sessions() -> None:
        from ..db import session_scope
        from sqlalchemy import select as sa_select

        with session_scope() as s:
            rows = s.execute(
                sa_select(ChatSession)
                .where(ChatSession.system_id == system.id, ChatSession.user_id == user.id)
                .order_by(ChatSession.created_at.desc())
                .limit(20)
            ).scalars().all()
        fingerprint = tuple(r.id for r in rows)
        if fingerprint == getattr(_load_sessions, "_last", None):
            return
        _load_sessions._last = fingerprint
        sessions_col.clear()
        with sessions_col:
            if not rows:
                ui.label("Nenhuma sessão ainda.").classes("text-xs text-gray-400")
            for r in rows:
                sess_id = r.id
                label = r.title or "sessão sem título"
                is_active = r.id == active_session["id"]
                btn_classes = "text-xs text-left w-full " + ("font-bold text-primary" if is_active else "text-gray-600")
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    ui.button(
                        label,
                        on_click=lambda sid=sess_id: _switch_session(sid),
                    ).props("flat dense align=left").classes(btn_classes + " grow")
                    if r.inference_revoked:
                        ui.icon("block").classes("text-xs text-red-500").tooltip("Inferência revogada")
                    else:
                        ui.button(
                            icon="block",
                            on_click=lambda sid=sess_id: _revoke_session_inference(sid),
                        ).props("flat dense round size=sm").tooltip("Revogar inferência desta sessão")

    def _revoke_session_inference(sess_id: str) -> None:
        from .common import notify
        from ..services.systems import revoke_session_inference

        try:
            revoke_session_inference(sess_id, user)
        except Exception as exc:  # noqa: BLE001 - feedback direto ao operador
            notify(str(exc), kind="negative")
            return
        notify("Inferência revogada para esta sessão.", kind="warning")
        _load_sessions._last = None
        _load_sessions()

    def _switch_session(sess_id: str) -> None:
        from ..db import session_scope
        from sqlalchemy import select as sa_select
        from ..models import RunEventRecord

        if active_session["id"] == sess_id:
            return
        active_session["id"] = sess_id
        current_run["id"] = None
        current_run["shown"] = 0
        log_box.clear()

        # Atualiza rótulo do título
        with session_scope() as s:
            cs = s.get(ChatSession, sess_id)
            title = cs.title if cs else ""
            session_title_label.set_text(title or "sessão sem título")

            # Carrega histórico de runs da sessão
            runs = s.execute(
                sa_select(AgentRun)
                .where(AgentRun.chat_session_id == sess_id, AgentRun.status != RunStatus.queued)
                .order_by(AgentRun.created_at)
            ).scalars().all()
            run_data = [(r.id, r.prompt, r.created_at) for r in runs]

        with log_box:
            for run_id, run_prompt, run_at in run_data:
                ui.chat_message(text=run_prompt, name=_sender_label("Você", run_at),
                                sent=True, avatar=_AVATAR_USER)
                _load_run_events(run_id)

        _load_sessions()

    def _new_session() -> None:
        from ..db import session_scope

        with session_scope() as s:
            cs = ChatSession(system_id=system.id, user_id=user.id, title="Nova sessão")
            s.add(cs)
            s.flush()
            sess_id = cs.id
        _switch_session(sess_id)

    def _start_rename() -> None:
        from ..db import session_scope

        if not active_session["id"]:
            return
        with session_scope() as s:
            cs = s.get(ChatSession, active_session["id"])
            rename_input.set_value(cs.title or "" if cs else "")
        rename_row.set_visibility(True)
        rename_state["editing"] = True

    def _confirm_rename() -> None:
        from ..db import session_scope

        if not active_session["id"]:
            rename_row.set_visibility(False)
            return
        new_title = (rename_input.value or "").strip()[:100]
        if new_title:
            with session_scope() as s:
                cs = s.get(ChatSession, active_session["id"])
                if cs is not None:
                    cs.title = new_title
            session_title_label.set_text(new_title)
        rename_row.set_visibility(False)
        rename_state["editing"] = False
        _load_sessions()

    # -------------------------------------------------------------------------
    # Lógica de envio e execução
    # -------------------------------------------------------------------------

    def do_send() -> None:
        text = (prompt.value or "").strip()
        if not text:
            return
        if current_run["id"] is not None:
            return
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

    approval_state: dict = {"signature": None}

    def _render_approval() -> None:
        from .. import gate

        run_id = current_run["id"]
        info = queue.pending_gates.get(run_id)
        question = queue.pending_questions.get(run_id)
        dbgate_pending = gate.list_pending_for_run(run_id) if run_id else []

        signature = (
            info["request_id"] if info else None,
            question["request_id"] if question else None,
            tuple(p["id"] for p in dbgate_pending),
        )
        if approval_state["signature"] == signature:
            return
        approval_state["signature"] = signature
        approval_box.clear()
        if info is None and question is None and not dbgate_pending:
            return
        with approval_box:
            if info is not None:
                with ui.card().classes("w-full border-orange-400"):
                    if info.get("sql") is not None:
                        ui.label("O agente pede aprovação para uma operação destrutiva").classes("font-semibold text-orange-700")
                        ui.label(f"SQL: {info['sql']}").classes("text-sm").style("white-space: pre-wrap")
                        ui.label(f"motivo: {info['reason']}").classes("text-xs text-gray-600")
                    else:
                        # permissão fora do domínio do gate de SQL (ex.: acesso a diretório
                        # fora do workspace) — não finge ser uma decisão de banco
                        ui.label("O agente pede permissão para uma ação fora do escopo usual").classes("font-semibold text-orange-700")
                        ui.label(f"tipo: {info.get('permission') or 'desconhecido'}").classes("text-sm")
                        if info.get("detail"):
                            ui.label(info["detail"]).classes("text-xs text-gray-600").style("white-space: pre-wrap")

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

            # pergunta que o próprio agente fez (ferramenta nativa `question`
            # do opencode) — sem gate nenhum decidindo, o modelo decidiu
            # perguntar por conta própria (achado ao vivo: run presa pra
            # sempre sem isto, não havia como responder pela UI)
            if question is not None:
                with ui.card().classes("w-full border-blue-400"):
                    ui.label(question.get("header") or "O agente tem uma pergunta").classes("font-semibold text-blue-700")
                    ui.label(question["question"]).classes("text-sm").style("white-space: pre-wrap")

                    def decide_question(label: str) -> None:
                        queue.decide_question(run_id, question["request_id"], label)

                    with ui.row():
                        for label in question.get("options", []):
                            ui.button(
                                label, on_click=lambda label=label: decide_question(label)
                            ).props("outline data-testid=question-option")

            # pendências do proxy de banco no data plane (sidecar, change
            # db-proxy-gate-data-plane) — a conexão fica segurada do outro lado
            # até decidir aqui; ao contrário do pedido acima, não há `reply_gate`
            # do harness envolvido, decide_request só muda o status no banco.
            for pending in dbgate_pending:
                with ui.card().classes("w-full border-orange-400"):
                    ui.label("O agente pede aprovação para uma operação destrutiva (proxy de banco)").classes(
                        "font-semibold text-orange-700"
                    )
                    ui.label(f"SQL: {pending['sql']}").classes("text-sm").style("white-space: pre-wrap")
                    ui.label(f"motivo: {pending['reason']}").classes("text-xs text-gray-600")
                    if pending.get("connection_name"):
                        ui.label(f"conexão: {pending['connection_name']}").classes("text-xs text-gray-600")

                    def decide_dbgate(approve: bool, request_id=pending["id"]) -> None:
                        from ..models import User as UserM
                        from ..db import session_scope

                        with session_scope() as s:
                            author = s.get(UserM, user.id)
                            author_id = author.id if author else None
                            author_email = author.email if author else ""
                        gate.decide_request(request_id, approve, author_id=author_id, author_email=author_email)

                    with ui.row():
                        ui.button(
                            "Aprovar", icon="check", on_click=lambda rid=pending["id"]: decide_dbgate(True, rid)
                        ).props("color=negative data-testid=dbgate-approve")
                        ui.button(
                            "Recusar", icon="close", on_click=lambda rid=pending["id"]: decide_dbgate(False, rid)
                        ).props("outline data-testid=dbgate-deny")

    def render_event(box, event) -> None:
        if event.kind in _QUIET_KINDS:
            return

        if event.kind in _STATUS_ICON:
            icon, color, label = _STATUS_ICON[event.kind]
            # o reset de contexto traz a própria mensagem já em português
            label_text = (event.text or label) if event.kind == "session_context_reset" else label
            with box, ui.row().classes("w-full justify-center items-center gap-1"):
                ui.icon(icon).classes(f"text-sm {color}")
                ui.label(label_text).classes(f"text-xs {color}")
            return

        if event.kind == "gate_request":
            permission = event.meta.get("permission") or ""
            if permission == "bash":
                command = event.meta.get("command") or event.text or "comando"
                text = f"PEDIDO DE APROVAÇÃO — comando de banco: {command}"
            else:
                detail = event.meta.get("command") or event.text or permission or "ação do agente"
                text = f"PEDIDO DE APROVAÇÃO — permissão '{permission or 'desconhecida'}': {detail}"
        elif event.kind == "question_asked":
            header = event.meta.get("header") or "pergunta do agente"
            text = f"PERGUNTA DO AGENTE — {header}: {event.text}"
        elif event.kind == "command_run":
            text = f"comando: {(event.meta.get('command') or event.text or 'comando')[:160]}"
        elif event.kind == "file_edited":
            files = event.meta.get("files") or ([event.meta["file"]] if event.meta.get("file") else [])
            names = ", ".join(f for f in files if f)
            detail = names or (event.text or "").strip()
            text = f"arquivo alterado: {detail}" if detail else "arquivo alterado"
        else:
            text = event.text or event.kind

        with box:
            row_classes = "w-full items-center gap-1" + (" af-debug" if event.kind in _DEBUG_KINDS else "")
            with ui.row().classes(row_classes):
                icon = _EVENT_ICON.get(event.kind)
                if icon:
                    ui.icon(icon).classes("text-gray-500")
                sender = _sender_label("Agente", getattr(event, "created_at", None))
                if event.kind == "message":
                    msg = ui.chat_message(name=sender, sent=False, avatar=_AVATAR_AGENT)
                    with msg:
                        for seg_kind, seg_raw in parse_artifacts(event.text or ""):
                            render_artifact_segment(msg, seg_kind, seg_raw)
                else:
                    msg = ui.chat_message(text=text, name=sender, sent=False, avatar=_AVATAR_AGENT)
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
            # queue.pending_gates reflete só o pedido ATUALMENTE pendente — ao contrário
            # de varrer o histórico do buffer, que continuaria "True" para sempre depois
            # que o editor já aprovou (o evento gate_request fica no buffer até o fim da run)
            from .. import gate

            aguardando_gate = queue.pending_gates.get(current_run["id"]) is not None or bool(
                gate.list_pending_for_run(current_run["id"])
            )
            aguardando_pergunta = queue.pending_questions.get(current_run["id"]) is not None
            if aguardando_pergunta:
                status_label = "o agente tem uma pergunta"
            elif aguardando_gate:
                status_label = "aguardando sua aprovação (gate de destrutivas)"
            else:
                status_label = "agente executando..."
            set_state(status_label, busy=True)
            _render_approval()
        else:
            if current_run["id"] is not None:
                buffer = queue.buffers.get(current_run["id"])
                if buffer:
                    events = buffer.snapshot()
                    for event in events[current_run["shown"]:]:
                        render_event(log_box, event)
                    current_run["shown"] = len(events)
            if position:
                set_state(f"{len(position)} pedido(s) na fila", busy=True)
            else:
                set_state("agente livre", busy=False)
            current_run["id"] = None
            interrupt_btn.set_visibility(False)
        if pending_prompt["text"] and state["running"] is None and not position:
            text = pending_prompt["text"]
            pending_prompt["text"] = None
            run = queue.enqueue(system.id, user.id, text, chat_session_id=active_session["id"])
            # atualiza sessão ativa com a sessão criada/usada na run
            active_session["id"] = run.chat_session_id
            current_run["id"] = run.id
            current_run["shown"] = 0
            with log_box:
                ui.chat_message(text=text, name=_sender_label("Você", datetime.now(timezone.utc)),
                                sent=True, avatar=_AVATAR_USER)
            _load_sessions()

    def _load_run_events(run_id: str) -> None:
        from ..db import session_scope
        from sqlalchemy import select as sa_select
        from ..models import RunEventRecord

        with session_scope() as s:
            events = s.execute(
                sa_select(RunEventRecord).where(RunEventRecord.run_id == run_id)
                .order_by(RunEventRecord.created_at)
            ).scalars().all()
        box = ui.column().classes("w-full gap-1 pl-4")
        for evt in events:
            render_event(box, evt)

    def on_debug_change() -> None:
        debug["on"] = bool(debug_switch.value)
        for el in (log_box,):
            if debug["on"]:
                el.classes(remove="af-hide-debug")
            else:
                el.classes(add="af-hide-debug")

    debug_switch.on_value_change(on_debug_change)

    _load_sessions()
    ui.timer(2.0, _load_sessions)
    ui.timer(0.5, refresh_state)
