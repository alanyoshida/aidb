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
    # tokens do tema direto por estilo em vez de classe Tailwind crua
    # (achado do critique: nomes de cor crus só funcionavam aqui por
    # depender de um remapeamento global coincidente — ver DESIGN.md)
    with box, ui.card().classes("w-full p-2").style(
        "border: 1px solid var(--ap-danger-border); background: var(--ap-danger-bg);"
    ):
        ui.label(f"Artifact inválido ({kind}): {err}").classes("text-xs font-medium").style("color: var(--ap-danger)")
        with ui.expansion("Ver conteúdo bruto").classes("text-xs").style("color: var(--ap-danger)"):
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
    active_session: dict = {"id": None, "blocked": False}  # ChatSession.id e se o contexto foi reiniciado
    rename_state: dict = {"editing": False}

    with ui.row().classes("w-full gap-4").style("flex-wrap: wrap; align-items: flex-start"):
        # --- sidebar de sessões, sempre visível ------------------------------
        # Coluna fixa à esquerda (pedido do operador, depois do critique): a
        # versão anterior (lista inline acima do título, com scroll limitado a
        # 150px) resolvia "esconder qual sessão está ativa", mas ainda
        # competia por espaço vertical com o resto do chat. Uma coluna própria
        # não compete com nada — sobra a largura toda do log pro conteúdo.
        # Abaixo de 700px (theme.py) ela vira um drawer deslizante; o fundo
        # escurecido (fecha ao tocar fora) só existe de verdade nessa largura.
        with ui.column().classes("gap-2 af-chat-sidebar").style("width: 256px; flex: none") as sidebar_col:
            ui.button("Nova sessão", icon="add", on_click=lambda: _new_session()).props(
                'flat dense no-caps data-testid=chat-new-session aria-label="Nova sessão"'
            ).classes("text-xs")
            ui.label("Sessões").classes("text-xs font-semibold text-gray-500")
            with ui.scroll_area().classes("w-full h-96"):
                sessions_col = ui.column().classes("w-full gap-1")
        sidebar_backdrop = ui.element("div").classes("af-chat-backdrop").on(
            "click", lambda: _close_sidebar()
        )

        # --- área principal do chat -------------------------------------------
        with ui.column().classes("grow gap-1").style("min-width: 0"):
            session_title_row = ui.row().classes("w-full items-center gap-1")
            with session_title_row:
                ui.button(icon="menu", on_click=lambda: _toggle_sidebar()).props(
                    'flat dense round data-testid=chat-sidebar-toggle '
                    'aria-label="Abrir lista de sessões"'
                ).classes("af-chat-sidebar-toggle")
                session_title_label = ui.label("").classes("text-sm font-medium text-gray-700 grow")
                rename_btn = ui.button(icon="edit", on_click=lambda: _start_rename()).props(
                    'flat dense round aria-label="Renomear esta sessão"'
                ).tooltip("Renomear esta sessão")
            # Botões de ícone (check/×) em vez de texto "OK"/"×": o "×" cru não
            # tinha aria-label nenhum (achado do critique — único ícone sem
            # nome acessível nesta tela) e os botões de texto, largos, ficavam
            # visualmente soltos na ponta do campo. Mesmo padrão já usado no
            # par Aprovar/Recusar do gate.
            rename_row = ui.row().classes("w-full items-center gap-1")
            rename_row.set_visibility(False)
            with rename_row:
                rename_input = ui.input("Novo título").classes("grow")
                ui.button(icon="check", on_click=lambda: _confirm_rename()).props(
                    'flat dense round aria-label="Confirmar novo título"'
                ).tooltip("Confirmar novo título")
                ui.button(icon="close", on_click=lambda: _cancel_rename()).props(
                    'flat dense round aria-label="Cancelar renomear"'
                ).tooltip("Cancelar renomear")

            # --- log do chat ---------------------------------------------------
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
            debug_switch = ui.switch("Debug").props("data-testid=chat-debug").tooltip(
                "Mostra os comandos executados e arquivos alterados pelo agente"
            )
            blocked_row = ui.row().classes("w-full items-center justify-center gap-2")
            blocked_row.set_visibility(False)
            with blocked_row:
                ui.icon("refresh").classes("text-sm text-amber-600")
                ui.label("Contexto do agente foi reiniciado nesta sessão.").classes("text-xs text-amber-600")
                # ação embutida no próprio aviso (achado do critique: a correção só
                # existia no botão do topo, fora do aviso — atrito extra bem na hora
                # em que o usuário já está frustrado)
                ui.button("Nova sessão", icon="add", on_click=lambda: _new_session()).props(
                    'flat dense no-caps aria-label="Nova sessão"'
                ).classes("text-xs text-amber-600")
            input_row = ui.row().classes("w-full items-center")
            with input_row:
                prompt = ui.input(placeholder="Peça algo ao agente (ex.: crie um CRUD da tabela clientes)").classes("grow af-chat-input").props(
                    'data-testid=chat-input borderless aria-label="Mensagem para o agente"'
                )
                send_btn = ui.button(icon="send").classes("af-chat-send").props(
                    'flat round data-testid=chat-send aria-label="Enviar mensagem"'
                ).tooltip("Enviar mensagem")
                interrupt_btn = ui.button(icon="stop").props(
                    'color=negative flat round data-testid=chat-interrupt aria-label="Interromper"'
                ).tooltip("Interromper")
                interrupt_btn.set_visibility(False)

    current_run: dict = {"id": None, "shown": 0}
    pending_prompt: dict = {"text": None}
    empty_hint: dict = {"el": None}  # placeholder de sessão nova sem runs ainda

    def _clear_empty_hint() -> None:
        if empty_hint["el"] is not None:
            empty_hint["el"].delete()
            empty_hint["el"] = None

    def _show_empty_hint(text: str) -> None:
        with ui.column().classes("w-full items-center justify-center gap-1").style(
            "padding: 32px 16px"
        ) as hint:
            ui.icon("chat_bubble_outline").classes("text-2xl text-gray-400")
            ui.label(text).classes("text-xs text-gray-400")
        empty_hint["el"] = hint

    def _toggle_sidebar() -> None:
        # só tem efeito visual abaixo de 700px (CSS em theme.py) — no desktop
        # a sidebar já é sempre visível e o botão fica escondido
        sidebar_col.classes(toggle="af-open")
        sidebar_backdrop.classes(toggle="af-open")

    def _close_sidebar() -> None:
        sidebar_col.classes(remove="af-open")
        sidebar_backdrop.classes(remove="af-open")

    def _update_input_blocked() -> None:
        blocked = active_session["blocked"]
        blocked_row.set_visibility(blocked)
        if blocked:
            prompt.disable()
            send_btn.disable()
        else:
            prompt.enable()
            send_btn.enable()

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
        # inclui a sessão ativa, o título e o estado de revogação no
        # fingerprint: sem a sessão ativa, trocar de sessão sem criar/remover
        # nenhuma (o caso comum) nunca re-renderizava a lista, e o destaque de
        # "sessão ativa" ficava preso na primeira renderização. Sem título e
        # revogação, renomear uma sessão não mudava o conjunto de ids — o
        # fingerprint ficava igual e a lista nunca re-renderizava, nem no
        # timer de 2s (achado ao vivo: "renomeei e deu OK, mas o nome na
        # sidebar não mudou").
        fingerprint = (
            active_session["id"],
            tuple((r.id, r.title, r.inference_revoked) for r in rows),
        )
        if fingerprint == getattr(_load_sessions, "_last", None):
            return
        _load_sessions._last = fingerprint
        sessions_col.clear()
        with sessions_col:
            if not rows:
                ui.label("Nenhuma sessão ainda.").classes("text-xs text-gray-400")
            for r in rows:
                sess_id = r.id
                base_label = r.title or "sessão sem título"
                # título + horário numa linha só, mesmo padrão "Nome · horário"
                # já usado pro remetente das mensagens (_sender_label) — a
                # primeira versão colocava o horário numa segunda linha abaixo
                # do título, mas sem nada separando um par título+horário do
                # próximo, ficava ambíguo de qual sessão era o horário de cima
                # ou de baixo (achado ao vivo do usuário).
                stamp = _stamp(r.created_at)
                label = f"{base_label} · {stamp}" if stamp else base_label
                is_active = r.id == active_session["id"]
                btn_classes = "text-xs text-left w-full " + ("font-bold text-primary" if is_active else "text-gray-600")
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    # color=None: sem isto o ui.button do NiceGUI aplica
                    # color='primary' por padrão (vira a classe .text-primary
                    # do Quasar) em cima do texto de QUALQUER sessão, mesmo
                    # inativa — a classe .text-gray-600 que marcamos pra
                    # inativa nunca vencia (achado ao vivo do critique: as
                    # duas sessões, ativa e inativa, renderizavam na mesma
                    # cor indigo; só o negrito diferenciava).
                    ui.button(
                        label, color=None,
                        on_click=lambda sid=sess_id: _switch_session(sid),
                    ).props("flat dense no-caps align=left").classes(
                        btn_classes + " grow af-session-btn"
                    ).style("min-width: 0")
                    if r.inference_revoked:
                        # "block" (sólido) só aqui, como estado permanente — o botão de
                        # ação usa um ícone diferente (achado do critique: o mesmo "block"
                        # pros dois ficava sobrecarregado, só funcionava pelo contexto)
                        ui.icon("block").classes("text-xs text-red-500").tooltip("Inferência revogada")
                    else:
                        ui.button(
                            icon="do_not_disturb_on",
                            on_click=lambda sid=sess_id: _revoke_session_inference(sid),
                        ).props(
                            'flat dense round size=sm aria-label="Revogar inferência desta sessão"'
                        ).tooltip("Revogar inferência desta sessão")

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

        # no mobile (drawer), escolher uma sessão deve revelar o chat por
        # trás — sem isto o drawer ficava aberto por cima da conversa
        _close_sidebar()
        if active_session["id"] == sess_id:
            return
        active_session["id"] = sess_id
        current_run["id"] = None
        current_run["shown"] = 0
        log_box.clear()
        empty_hint["el"] = None  # log_box.clear() já removeu o elemento do DOM

        # Atualiza rótulo do título
        with session_scope() as s:
            cs = s.get(ChatSession, sess_id)
            title = cs.title if cs else ""
            session_title_label.set_text(title or "sessão sem título")
            # context_reset: container foi recriado (edição de conexão, provedor,
            # etc.) desde a última mensagem desta sessão — harness_session_id
            # já foi descartado, então reaproveitar daria um contexto vazio sem
            # avisar. Bloqueia o envio até o usuário criar uma sessão nova.
            active_session["blocked"] = bool(cs.context_reset) if cs else False

            # Carrega histórico de runs da sessão
            runs = s.execute(
                sa_select(AgentRun)
                .where(AgentRun.chat_session_id == sess_id, AgentRun.status != RunStatus.queued)
                .order_by(AgentRun.created_at)
            ).scalars().all()
            run_data = [(r.id, r.prompt, r.created_at, r.status) for r in runs]

        with log_box:
            if not run_data:
                # sessão nova: o log em branco só com o placeholder do input não
                # orientava quem chega aqui pela primeira vez (achado do critique).
                _show_empty_hint("Comece digitando uma mensagem para o agente.")
            for run_id, run_prompt, run_at, run_status in run_data:
                ui.chat_message(text=run_prompt, name=_sender_label("Você", run_at),
                                sent=True, avatar=_AVATAR_USER)
                # Uma run ainda em andamento (running/awaiting_approval) não
                # tem seus eventos recarregados aqui — refresh_state() já
                # faz esse replay a partir do buffer ao vivo assim que
                # running_here vira True logo em seguida. Recarregar os dois
                # duplicava cada evento (achado ao vivo do critique: mesmo
                # "comando: ..." aparecendo duas vezes ao trocar pra uma
                # sessão com run ativa).
                if run_status not in (RunStatus.running, RunStatus.awaiting_approval):
                    _load_run_events(run_id)

        _update_input_blocked()
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

    def _cancel_rename() -> None:
        rename_row.set_visibility(False)
        rename_state["editing"] = False

    # -------------------------------------------------------------------------
    # Lógica de envio e execução
    # -------------------------------------------------------------------------

    def do_send() -> None:
        if active_session["blocked"]:
            return
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
        run_id = current_run["id"]
        info = queue.pending_gates.get(run_id)
        question = queue.pending_questions.get(run_id)

        signature = (
            info["request_id"] if info else None,
            question["request_id"] if question else None,
        )
        if approval_state["signature"] == signature:
            return
        approval_state["signature"] = signature
        approval_box.clear()
        if info is None and question is None:
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

                    # "Aprovar" deixa a operação destrutiva seguir — não é o botão
                    # seguro. `color=negative` (vermelho) nele lia como "pare/não"
                    # bem no botão que na verdade diz "sim, prossiga" (achado do
                    # critique: ambíguo no momento de maior risco da tela). Nenhum
                    # dos dois leva cor semântica agora — a borda laranja do card já
                    # avisa "atenção"; a decisão em si vem só do texto/ícone.
                    with ui.row():
                        ui.button("Aprovar", icon="check", on_click=lambda: decide(True)).props("outline data-testid=gate-approve")
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
            command = (event.meta.get("command") or event.text or "comando")[:160]
            # "status" vem do harness só pra isto: distinguir o comando ainda rodando
            # (sem output ainda) do mesmo comando já concluído — sem isto os dois
            # eventos (legitimamente diferentes) renderizavam o mesmo texto e pareciam
            # duplicados no log de debug. Falta de status (eventos históricos antigos,
            # já sempre finais) cai no rótulo de concluído.
            status = event.meta.get("status") or "completed"
            prefix = "executando" if status in ("pending", "running") else "comando"
            text = f"{prefix}: {command}"
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
        # o sistema só processa uma run por vez — ela sempre pertence a UMA
        # sessão, nunca necessariamente à que está sendo exibida agora (achado
        # do critique: trocar de sessão sem isto vazava a run de outra sessão
        # pro log_box e pro approval_box desta aqui)
        running_here = state["running"] is not None and state["running_session_id"] == active_session["id"]
        if not running_here and active_session["id"] is None and state["running"] is not None:
            # pouso na página sem ter clicado em nenhuma sessão ainda: acompanha
            # a run em andamento em vez de ficar sem título nem sessão nenhuma
            # (achado do critique: título ficava em branco neste caso)
            from ..db import session_scope as _session_scope

            active_session["id"] = state["running_session_id"]
            with _session_scope() as s:
                cs = s.get(ChatSession, active_session["id"])
                session_title_label.set_text((cs.title if cs else "") or "sessão sem título")
                active_session["blocked"] = bool(cs.context_reset) if cs else False
            _update_input_blocked()
            _load_sessions()
            running_here = True
        elif active_session["id"] is None and empty_hint["el"] is None:
            # pouso na página sem sessão ativa e sem nada rodando em lugar
            # nenhum: o placeholder de "sessão vazia" só existia um degrau
            # abaixo disso, depois de escolher uma sessão — a primeira
            # pintura da aba ficava sem nenhuma orientação (achado do
            # critique). `empty_hint["el"] is None` evita recriar o
            # placeholder a cada tick do timer de 0.5s.
            with log_box:
                _show_empty_hint("Selecione uma sessão ou crie uma nova para começar.")
        if running_here:
            if current_run["id"] != state["running"]:
                current_run["id"] = state["running"]
                current_run["shown"] = 0
                log_box.clear()
                empty_hint["el"] = None  # log_box.clear() já removeu o elemento do DOM
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
            aguardando_gate = queue.pending_gates.get(current_run["id"]) is not None
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
            if state["running"] is not None:
                set_state("agente ocupado em outra sessão", busy=True)
            elif position:
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
            _clear_empty_hint()
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
