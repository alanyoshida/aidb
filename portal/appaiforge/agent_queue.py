"""Fila de execução: um agente por sistema por vez (spec agent-harness).

Runs enfileiradas por ordem de chegada; worker por sistema executa em série.
Eventos vão para assinantes em memória (chat) e o resumo persiste na run.
"""

import json
import logging
import re
import threading
from collections import deque

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .harness.base import HarnessPort, RunEvent, SessionExpiredError
from .harness.fake import FakeHarness
from .harness.opencode import OpencodeHarness
from .models import AgentRun, ChatSession, RunStatus, TokenUsage, System, User, utcnow

log = logging.getLogger(__name__)


def reconcile_orphaned_runs() -> int:
    """Marca como falhas as runs 'running'/'awaiting_approval' sem worker vivo.

    Chamada no boot do portal: um restart do processo mata as threads worker,
    mas o status da run no banco fica preso em 'running' para sempre — sem
    isso, a fila daquele sistema trava e nenhuma run nova é processada.
    Retorna a quantidade de runs recuperadas.
    """
    with session_scope() as s:
        stuck = s.execute(
            select(AgentRun).where(AgentRun.status.in_([RunStatus.running, RunStatus.awaiting_approval]))
        ).scalars().all()
        for run in stuck:
            run.status = RunStatus.failed
            run.summary = "execução interrompida por reinício do portal"
            run.finished_at = utcnow()
        count = len(stuck)
    if count:
        log.warning("reconciliação: %d run(s) órfã(s) marcada(s) como falha no boot", count)
    return count


_REDACT_PATTERNS = [
    # connection strings com credencial: postgresql://user:senha@host -> ***@host
    (re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://([^:/@\s]+):([^@\s]+)@"), r"\1:***@"),
    # senhas/chaves/tokens em querystring, envs e flags
    (re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|api[_-]?key|senha)\s*[=:]\s*\"?[^\s&\"']+\"?"), r"\1=***"),
]


def _derive_title(prompt: str, max_chars: int = 50) -> str:
    """Título automático de sessão: primeiras palavras do prompt, até max_chars."""
    text = prompt.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "…"


def redact(text: str) -> str:
    """Mascara credenciais em textos que vão para o chat/auditoria (spec db-connections:
    nenhum evento contém senha ou connection string completa)."""
    if not text:
        return text
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _event_key(event: RunEvent) -> tuple:
    """Identidade de um evento para deduplicação (ver _dispatch): o harness opencode
    reemite o mesmo estado de uma tool call (ou o mesmo uso de tokens) em updates
    sucessivos do SSE — sem isso, o mesmo comando/uso aparece repetido no chat e na
    auditoria (TokenUsage somado em dobro)."""
    try:
        meta_repr = json.dumps(event.meta or {}, sort_keys=True, default=str)
    except TypeError:
        meta_repr = repr(event.meta)
    return (event.kind, event.text, meta_repr)


class RunBuffer:
    """Buffer thread-safe dos eventos de uma run para assinantes (chat UI)."""

    def __init__(self):
        self.events: deque[RunEvent] = deque(maxlen=500)
        self.lock = threading.Lock()

    def push(self, event: RunEvent) -> None:
        with self.lock:
            self.events.append(event)

    def snapshot(self) -> list[RunEvent]:
        with self.lock:
            return list(self.events)


class AgentQueue:
    def __init__(self, harness: HarnessPort):
        self.harness = harness
        self.buffers: dict[str, RunBuffer] = {}
        self.pending_gates: dict[str, dict] = {}  # run_id -> pedido de gate pendente
        self.pending_questions: dict[str, dict] = {}  # run_id -> pergunta do agente pendente (ferramenta question)
        self._workers: set[str] = set()
        self._lock = threading.Lock()

    def harness_for(self, system: System) -> HarnessPort:
        return self.harness

    def enqueue(self, system_id: str, user_id: str, prompt: str, chat_session_id: str | None = None) -> AgentRun:
        with session_scope() as s:
            user = s.get(User, user_id)
            user_email = user.email if user is not None else ""
            if chat_session_id is not None:
                chat = s.get(ChatSession, chat_session_id)
                if chat is None or chat.system_id != system_id or chat.user_id != user_id:
                    chat = None
            else:
                chat = None
            if chat is None:
                title = _derive_title(prompt)
                chat = ChatSession(system_id=system_id, user_id=user_id, title=title)
                s.add(chat)
                s.flush()
            run = AgentRun(system_id=system_id, user_id=user_id, user_email=user_email, chat_session_id=chat.id, prompt=prompt)
            s.add(run)
            s.flush()
            s.expunge(run)

        self._kick(system_id)
        return run

    def system_state(self, system_id: str) -> dict:
        """Estado da fila para exibição: run corrente + fila de espera.

        `running_session_id` existe pra quem exibe várias sessões de chat do
        mesmo sistema (UI) distinguir "a run corrente é desta sessão que estou
        vendo" de "o sistema está ocupado numa sessão diferente" — o sistema só
        processa uma run por vez, então a run corrente sempre pertence a UMA
        sessão só, nunca à sessão que o editor porventura esteja olhando."""
        with session_scope() as s:
            runs = s.execute(
                select(AgentRun)
                .where(
                    AgentRun.system_id == system_id,
                    AgentRun.status.in_([RunStatus.queued, RunStatus.running, RunStatus.awaiting_approval]),
                )
                .order_by(AgentRun.created_at)
            ).scalars().all()
            out = {"running": None, "running_session_id": None, "queued": []}
            for r in runs:
                if r.status in (RunStatus.running, RunStatus.awaiting_approval) and out["running"] is None:
                    out["running"] = r.id
                    out["running_session_id"] = r.chat_session_id
                elif r.status == RunStatus.queued:
                    out["queued"].append(r.id)
            return out

    def _kick(self, system_id: str) -> None:
        with self._lock:
            if system_id in self._workers:
                return  # worker atual vai pegar a próxima da fila ao terminar
            with session_scope() as s:
                next_run = s.execute(
                    select(AgentRun.id)
                    .where(AgentRun.system_id == system_id, AgentRun.status == RunStatus.queued)
                    .order_by(AgentRun.created_at)
                    .limit(1)
                ).scalar_one_or_none()
            if next_run is None:
                return
            self._workers.add(system_id)
        threading.Thread(target=self._work, args=(system_id, next_run), daemon=True, name=f"agent-{system_id}").start()

    def _work(self, system_id: str, run_id: str) -> None:
        while True:
            try:
                self._execute(system_id, run_id)
            except Exception:
                # falha de UMA run não pode matar o worker do sistema
                log.exception("execução da run %s falhou no worker", run_id)
            with self._lock:
                with session_scope() as s:
                    next_run = s.execute(
                        select(AgentRun.id)
                        .where(AgentRun.system_id == system_id, AgentRun.status == RunStatus.queued)
                        .order_by(AgentRun.created_at)
                        .limit(1)
                    ).scalar_one_or_none()
                if next_run is None:
                    self._workers.discard(system_id)
                    return
                run_id = next_run

    def _execute(self, system_id: str, run_id: str) -> None:
        from . import checkpoints, guidelines

        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            system = s.get(System, system_id)
        if run is None or system is None:
            # run apagada sob o worker (ex.: reset da suíte E2E) — segue para a próxima
            log.warning("run %s/system %s não existem mais", run_id, system_id)
            self.pending_gates.pop(run_id, None)
            self.buffers.pop(run_id, None)
            return
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            system = s.get(System, system_id)
            run.status = RunStatus.running
            run.started_at = utcnow()
            system_dict = {"system_id": system.id, "slug": system.slug, "provider": system.provider, "model": system.model}
            # sem expunge aqui: expurgar antes do commit descartaria o UPDATE de status

        # guidelines vigentes entram no workspace antes da execução (spec agent-harness)
        try:
            guidelines.materialize(system)
        except OSError:
            log.warning("não foi possível materializar AGENTS.md para %s", system.slug)

        buffer = RunBuffer()
        self.buffers[run_id] = buffer

        # Resolve sessão opencode: reutiliza existente salvo no ChatSession ou cria nova.
        with session_scope() as s:
            ar = s.get(AgentRun, run_id)
            cs = s.get(ChatSession, ar.chat_session_id) if ar.chat_session_id else None
            existing_session_id = cs.harness_session_id if cs else None
            needs_reset = bool(cs and cs.context_reset)

        if needs_reset or not existing_session_id:
            if needs_reset:
                buffer.push(RunEvent("session_context_reset", text="Contexto do agente reiniciado (container recriado)"))
            session_id = self.harness.create_session(system_dict)
        else:
            session_id = existing_session_id

        with session_scope() as s:
            ar = s.get(AgentRun, run_id)
            cs = s.get(ChatSession, ar.chat_session_id) if ar and ar.chat_session_id else None
            if cs is not None:
                cs.harness_session_id = session_id
                cs.context_reset = False

        # Por kind, não por slot único: um "command_run" repetido com um
        # "tool_output"/"usage" (ambos silenciosos no chat, _QUIET_KINDS) no
        # meio continuava passando pelo dedup, porque o slot único só lembra
        # do ÚLTIMO evento despachado, de qualquer kind — achado ao vivo do
        # critique (mesmo "comando: ..." duplicado no log de debug, com um
        # evento invisível no meio quebrando a memória do dedup).
        last_dispatched: dict = {}

        def on_event(event: RunEvent) -> None:
            try:
                _dispatch(event)
            except Exception:
                log.exception("falha ao tratar evento %s da run %s", event.kind, run_id)
                buffer.push(RunEvent("run_error", text=f"falha interna no portal ao tratar {event.kind}"))

        def _dispatch(event: RunEvent) -> None:
            event.text = redact(event.text)
            if event.meta.get("command"):
                event.meta["command"] = redact(event.meta["command"])
            if event.kind == "gate_request":
                self._handle_gate_request(system_dict, run_id, run.user_id, run.user_email, event, buffer, session_id)
                return
            if event.kind == "question_asked":
                self._handle_question_asked(system_dict, run_id, event, buffer, session_id)
                return
            # tool em progresso: opencode manda o "pending" antes de preencher o comando —
            # nada para mostrar ainda (o próximo update deste mesmo comando chega em seguida)
            if event.kind == "command_run" and not (event.meta.get("command") or "").strip():
                return
            # opencode também reemite "usage" com zeros depois do uso real do mesmo turno
            if event.kind == "usage" and not (event.meta.get("input_tokens") or event.meta.get("output_tokens")):
                return
            # opencode reemite o mesmo estado (ex.: a cada tick de uma tool em andamento,
            # ou o mesmo "usage" duas vezes) — sem isto, o comando aparece duplicado no
            # chat e o uso de tokens é contado em dobro na auditoria. Compara só contra o
            # último evento do MESMO kind (não o último de qualquer kind): um "tool_output"
            # ou "usage" silencioso entre dois "command_run" iguais não deve resetar a
            # memória do dedup pro kind que importa.
            key = _event_key(event)
            if last_dispatched.get(event.kind) == key:
                return
            last_dispatched[event.kind] = key
            buffer.push(event)
            if event.kind == "usage":
                # nem todo provedor reporta modelo no evento; cai para o config do sistema
                provider = event.meta.get("provider") or system_dict["provider"]
                model = event.meta.get("model") or system_dict["model"]
                with session_scope() as s_:
                    s_.add(TokenUsage(
                        run_id=run_id,
                        system_id=system_id,
                        user_id=run.user_id,
                        user_email=run.user_email,
                        provider=provider,
                        model=model,
                        input_tokens=event.meta.get("input_tokens", 0),
                        output_tokens=event.meta.get("output_tokens", 0),
                    ))

        final: RunEvent | None = None
        try:
            self.harness.run(system_dict, session_id, run.prompt, on_event)
        except SessionExpiredError:
            # sessão morta detectada ao enviar: reinicia com nova sessão e reexecuta
            log.warning("sessão opencode expirada na run %s; criando nova sessão", run_id)
            buffer.push(RunEvent("session_context_reset", text="Contexto do agente reiniciado (sessão expirada)"))
            session_id = self.harness.create_session(system_dict)
            with session_scope() as s:
                ar = s.get(AgentRun, run_id)
                cs = s.get(ChatSession, ar.chat_session_id) if ar and ar.chat_session_id else None
                if cs is not None:
                    cs.harness_session_id = session_id
                    cs.context_reset = False
            try:
                self.harness.run(system_dict, session_id, run.prompt, on_event)
            except Exception as exc:
                log.exception("run %s falhou após reinício de sessão", run_id)
                buffer.push(RunEvent("run_error", text=str(exc)))
        except Exception as exc:
            log.exception("run %s falhou no harness", run_id)
            buffer.push(RunEvent("run_error", text=str(exc)))
        for event in reversed(buffer.snapshot()):
            if event.kind in ("run_error", "run_interrupted"):
                final = event
                break
        if final is None:
            for event in reversed(buffer.snapshot()):
                if event.kind == "run_finished":
                    final = event
                    break

        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                return  # run apagada sob o worker (reset) — nada a persistir
            if final is not None and final.kind == "run_interrupted":
                run.status = RunStatus.interrupted
            elif final is not None and final.kind == "run_error":
                run.status = RunStatus.failed
                run.summary = final.text
            elif final is not None:
                assistant_events = [e for e in buffer.snapshot() if e.kind in ("message", "file_edited", "command_run", "usage")]
                if not assistant_events:
                    # provedor não produziu nada (ex.: chave sem saldo/rejeitada) — não é sucesso
                    run.status = RunStatus.failed
                    run.summary = "o provedor de LLM não retornou resposta (verifique chave, saldo e modelo configurados)"
                else:
                    run.status = RunStatus.succeeded
                    run.summary = final.meta.get("summary") or next(
                        (e.text for e in reversed(buffer.snapshot()) if e.kind == "message"), ""
                    )
            else:
                run.status = RunStatus.failed
                run.summary = "execução terminou sem conclusão"
            run.finished_at = utcnow()
            succeeded = run.status == RunStatus.succeeded
            user_id = run.user_id

        # Persistir eventos para consulta futura (correção do chat ao fazer F5)
        self._persist_events(run_id, buffer)

        if succeeded:
            # checkpoint da execução + publicação da app (ADR 0009, spec app-serving)
            from .services.systems import get_system

            fresh = get_system(system_id)
            if fresh is not None:
                from .models import User as UserM

                with session_scope() as s:
                    author = s.get(UserM, user_id)
                    if author is not None:
                        s.expunge(author)
                try:
                    checkpoints.record_checkpoint(fresh, run_id, run.summary or run.prompt[:80], author)
                except Exception:
                    log.exception("checkpoint falhou para %s", fresh.slug)
                try:
                    from .edge import publish_app

                    publish_app(fresh)
                except OSError:
                    log.warning("não foi possível publicar rota para %s", fresh.slug)

    def _handle_gate_request(self, system_dict: dict, run_id: str, user_id: str, user_email: str, event: RunEvent, buffer: RunBuffer, session_id: str) -> None:
        """Pedido de permissão do harness: o portal classifica e decide (D2).

        bloqueada -> recusa automática; normal -> aprova automática; confirmável
        -> pendência aguardando o editor no chat (estado awaiting_approval).

        O harness (opencode) pede permissão para mais coisas do que comando de
        banco via bash — por exemplo acesso a diretório fora do workspace
        (`permission: "external_directory"`). Só "bash" passa pelo classificador
        de SQL (ADR 0017); qualquer outro tipo vira uma pendência genérica, sem
        fingir que é uma decisão de banco (`sql=None`: `decide_gate` não grava
        no histórico do gate de destrutivas por não ser uma decisão de SQL).
        """
        from . import gate

        request_id = event.meta.get("request_id", "")
        permission = event.meta.get("permission", "")
        system_id = system_dict["system_id"]

        if permission != "bash":
            self.pending_gates[run_id] = {
                "request_id": request_id,
                "session_id": session_id,
                "sql": None,
                "permission": permission,
                "detail": event.text or permission or "ação do agente",
                "connection_name": "",
                "reason": "",
                "system_id": system_id,
                "system_slug": system_dict["slug"],
            }
            with session_scope() as s:
                run = s.get(AgentRun, run_id)
                if run is not None:
                    run.status = RunStatus.awaiting_approval
            buffer.push(event)
            return

        command = event.text
        sql = gate.extract_sql(command)

        if sql is None:
            classification, reason = gate.GateClass.CONFIRMABLE, "comando de banco sem SQL identificável"
        else:
            classification, reason = gate.classify_sql(sql)

        if classification is gate.GateClass.BLOCKED:
            self.harness.reply_gate(system_dict, session_id, request_id, approve=False)
            gate.record_decision(system_id, sql or command, origin="agente",
                                 connection_name="", classification=classification,
                                 decision="bloqueada", run_id=run_id, author_id=user_id, author_email=user_email)
            buffer.push(RunEvent("gate_denied", text=f"bloqueada pelo gate: {reason}", meta={"request_id": request_id}))
            return

        if classification is gate.GateClass.NORMAL:
            self.harness.reply_gate(system_dict, session_id, request_id, approve=True)
            gate.record_decision(system_id, sql, origin="agente",
                                 connection_name="", classification=classification,
                                 decision="aprovada", run_id=run_id, author_id=user_id, author_email=user_email)
            buffer.push(RunEvent("gate_approved", text=f"liberada pelo gate: {sql[:80]}", meta={"request_id": request_id}))
            return

        # confirmável: pendência — editor decide no chat
        self.pending_gates[run_id] = {
            "request_id": request_id,
            "session_id": session_id,
            "sql": sql or command,
            "connection_name": "",
            "reason": reason,
            "system_id": system_id,
            "system_slug": system_dict["slug"],
        }
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run is not None:
                run.status = RunStatus.awaiting_approval
        buffer.push(event)

    def _handle_question_asked(self, system_dict: dict, run_id: str, event: RunEvent, buffer: RunBuffer, session_id: str) -> None:
        """Pergunta que o próprio agente fez (ferramenta nativa `question` do
        opencode) — distinta do pedido de permissão (`gate_request`): aqui
        não há gate nenhum decidindo, o modelo decidiu perguntar por conta
        própria (achado ao vivo: pediu confirmação de um DELETE sem WHERE
        por iniciativa dele, não porque o portal pediu). Sem isto, a run
        ficava presa pra sempre — não existia como responder pela UI."""
        request_id = event.meta.get("request_id", "")
        self.pending_questions[run_id] = {
            "request_id": request_id,
            "session_id": session_id,
            "system_slug": system_dict["slug"],
            "header": event.meta.get("header", ""),
            "question": event.text,
            "options": event.meta.get("options", []),
        }
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run is not None:
                run.status = RunStatus.awaiting_approval
        buffer.push(event)

    def decide_gate(self, run_id: str, request_id: str, approve: bool, user) -> bool:
        """Decisão do editor sobre um pedido confirmável (spec destructive-gate)."""
        from . import gate
        from .models import User as UserM

        info = self.pending_gates.get(run_id)
        if info is None or info["request_id"] != request_id:
            return False
        with session_scope() as s:
            author = s.get(UserM, user.id) if user is not None else None
            if author is not None:
                s.expunge(author)
        self.harness.reply_gate({"slug": info["system_slug"]}, info["session_id"], request_id, approve)
        # pendências sem SQL (permissão fora do domínio do gate, ex.: acesso a
        # diretório) não entram no histórico de decisões de banco — gravar ali
        # seria uma decisão de SQL inventada, sem statement nenhuma por trás
        if info["sql"] is not None:
            gate.record_decision(
                info["system_id"], info["sql"], origin="agente", connection_name=info["connection_name"],
                classification=gate.GateClass.CONFIRMABLE,
                decision="aprovada" if approve else "recusada", run_id=run_id,
                author_id=author.id if author else None, author_email=author.email if author else None,
            )
        self.pending_gates.pop(run_id, None)
        buffer = self.buffers.get(run_id)
        if buffer:
            label = info["sql"][:80] if info["sql"] is not None else info.get("detail", "")
            buffer.push(RunEvent("gate_resolved", text=f"{'aprovada' if approve else 'recusada'} pelo editor: {label}"))
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run is not None and run.status == RunStatus.awaiting_approval:
                run.status = RunStatus.running
        return True

    def decide_question(self, run_id: str, request_id: str, label: str) -> bool:
        """Resposta do editor a uma pergunta que o agente fez por conta
        própria — sem gate nenhum envolvido, não gera GateDecision (não é
        uma decisão sobre SQL, é só repassar a escolha pro opencode)."""
        info = self.pending_questions.get(run_id)
        if info is None or info["request_id"] != request_id:
            return False
        self.harness.reply_question({"slug": info["system_slug"]}, info["session_id"], request_id, label)
        self.pending_questions.pop(run_id, None)
        buffer = self.buffers.get(run_id)
        if buffer:
            buffer.push(RunEvent("question_resolved", text=f"respondida pelo editor: {label}"))
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            if run is not None and run.status == RunStatus.awaiting_approval:
                run.status = RunStatus.running
        return True

    def interrupt(self, run_id: str, system: System) -> None:
        # pedido pendente é recusado quando a run é interrompida
        pending = self.pending_gates.pop(run_id, None)
        if pending is not None:
            from . import gate

            self.harness.reply_gate({"slug": system.slug}, pending["session_id"], pending["request_id"], approve=False)
            if pending["sql"] is not None:
                gate.record_decision(
                    system.id, pending["sql"], origin="agente", connection_name=pending["connection_name"],
                    classification=gate.GateClass.CONFIRMABLE, decision="recusada",
                    run_id=run_id, author_id=None,
                )
            buffer = self.buffers.get(run_id)
            if buffer:
                buffer.push(RunEvent("gate_resolved", text="recusada: execução interrompida"))
        pending_question = self.pending_questions.pop(run_id, None)
        if pending_question is not None:
            self.harness.reject_question(
                {"slug": system.slug}, pending_question["session_id"], pending_question["request_id"]
            )
            buffer = self.buffers.get(run_id)
            if buffer:
                buffer.push(RunEvent("question_resolved", text="rejeitada: execução interrompida"))
        with session_scope() as s:
            run = s.get(AgentRun, run_id)
            session_id = None
            if run is not None and run.chat_session_id:
                cs = s.get(ChatSession, run.chat_session_id)
                session_id = cs.harness_session_id if cs else None
        if session_id:
            self.harness.interrupt({"slug": system.slug}, session_id)
        from . import broker

        broker.cancel_inference(run_id)

    def _persist_events(self, run_id: str, buffer: RunBuffer) -> None:
        """Salvar eventos do buffer no banco para recuperação após F5."""
        from .models import RunEventRecord

        events = buffer.snapshot()
        if not events:
            return
        with session_scope() as s:
            for event in events:
                record = RunEventRecord(
                    run_id=run_id,
                    kind=event.kind,
                    text=event.text,
                    meta=event.meta or {},
                )
                s.add(record)


_queue: AgentQueue | None = None


def _harness_url(system: dict) -> str:
    from .config import get_settings
    from .edge import system_container_name

    return f"http://{system_container_name(system['slug'])}:{get_settings().opencode_port}"


def get_queue() -> AgentQueue:
    global _queue
    if _queue is None:
        settings = get_settings()
        if settings.harness_mode == "fake":
            harness = FakeHarness(settings.workspaces_dir)
        else:
            harness = OpencodeHarness(_harness_url)
        _queue = AgentQueue(harness)
    return _queue
