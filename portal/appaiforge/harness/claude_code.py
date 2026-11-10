"""Adapter do harness claude-code (ADR 0004; change add-claude-code-agent-profile).

Fala com o shim HTTP do container (`base-image/claude-code-shim/shim.py`),
não com a CLI `claude` direto — o shim é quem invoca a CLI por prompt e
devolve os eventos. Endpoints usados (mesma forma que `OpencodeHarness` usa
`opencode serve`, pro dispatch de `agent_queue.HARNESS_IMPLEMENTATIONS` não
precisar conhecer a diferença):

- POST /session                 -> cria sessão lógica
- POST /session/{id}/prompt     -> dispara prompt sem bloquear
- GET  /event                   -> SSE global (shape bruto do stream-json da
                                    CLI, só com "session_id" reescrito pelo
                                    shim - `_normalize` interpreta o shape)
- POST /session/{id}/abort      -> interrompe

Achados do spike real (tasks.md, task 1.1-1.4):
  - cada content block de um turno chega como um evento "assistant" PRÓPRIO.
  - `tool_use` (pedido) e `tool_result` (resultado) chegam em eventos
    separados ("assistant" e "user"); não tem o conceito de update
    pendente/rodando/concluído do mesmo evento que o opencode tem.
  - evento terminal sempre `{"type":"result", "subtype": ..., "is_error": ...}`.

Decisão de escopo (D do design, non-goal explícito): `reply_gate`/
`reply_question`/`reject_question` são no-op documentado - a CLI headless
não expõe um protocolo de permissão assíncrono equivalente ao
`permission.asked`/`question.asked` do opencode, e o gate de SQL destrutivo
já opera no data plane (proxy de conexão ao banco), agnóstico do protocolo
de permissão do agente (spec destructive-gate)."""

import json
import logging
from typing import Callable

import httpx

from .base import HarnessPort, RunEvent, SessionExpiredError

log = logging.getLogger(__name__)

# Nomes das ferramentas nativas do claude-code (maiúscula, ao contrário do
# opencode) - achado real do spike (evento system/init, campo "tools").
_TOOL_KIND = {
    "edit": "file_edited",
    "write": "file_edited",
    "bash": "command_run",
}


class ClaudeCodeHarness(HarnessPort):
    def __init__(self, resolve_base_url: Callable[[dict], str], timeout: float = 30.0):
        self.resolve_base_url = resolve_base_url
        self.timeout = timeout
        self._aborting: set[str] = set()
        # toolu_id -> nome da ferramenta, populado pelo evento "assistant"
        # com o tool_use; o evento "user" com o tool_result correspondente só
        # carrega o id, não o nome (achado real do spike).
        self._tool_names: dict[str, str] = {}

    def create_session(self, system: dict) -> str:
        base = self.resolve_base_url(system)
        resp = httpx.post(f"{base}/session", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["id"]

    def interrupt(self, system: dict, session_id: str) -> None:
        self._aborting.add(session_id)
        try:
            base = self.resolve_base_url(system)
            httpx.post(f"{base}/session/{session_id}/abort", timeout=self.timeout)
        except httpx.HTTPError:
            pass

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        """No-op documentado: a CLI headless não tem protocolo de permissão
        assíncrono (o gate de SQL destrutivo já é agnóstico disso, no data
        plane - spec destructive-gate). Nunca chamado de verdade hoje (o
        normalize deste harness nunca emite `gate_request`), mantido só pra
        satisfazer o contrato de HarnessPort sem lançar."""
        return None

    def reply_question(self, system: dict, session_id: str, request_id: str, label: str) -> None:
        """No-op documentado: sem equivalente à ferramenta nativa `question`
        do opencode nesta CLI headless (non-goal explícito do design)."""
        return None

    def reject_question(self, system: dict, session_id: str, request_id: str) -> None:
        return None

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started", meta={"session_id": session_id}))
        base = self.resolve_base_url(system)
        payload: dict = {"prompt": prompt}
        if system.get("model"):
            payload["model"] = system["model"]
        resp = httpx.post(f"{base}/session/{session_id}/prompt", json=payload, timeout=self.timeout)
        if resp.status_code == 404:
            raise SessionExpiredError(f"sessão claude-code {session_id!r} não existe mais")
        resp.raise_for_status()

        try:
            with httpx.stream("GET", f"{base}/event", timeout=None) as sse:
                for line in sse.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        envelope = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if envelope.get("session_id") != session_id:
                        continue
                    for event in self._normalize(envelope, system):
                        on_event(event)
                    if envelope.get("type") == "result":
                        return
        except httpx.HTTPError as exc:
            if session_id in self._aborting:
                on_event(RunEvent("run_interrupted"))
            else:
                on_event(RunEvent("run_error", text=f"falha de comunicação com o harness: {exc}"))
        finally:
            self._aborting.discard(session_id)

    def _normalize(self, envelope: dict, system: dict) -> list[RunEvent]:
        """Devolve uma lista (nunca um RunEvent solto): o evento "result" é o
        único caso que carrega duas coisas ao mesmo tempo (uso de tokens +
        sinal terminal do turno), e `run()` trata as duas sempre do mesmo
        jeito, por mais que os outros tipos de evento só gerem 0 ou 1."""
        etype = envelope.get("type")

        if etype == "assistant":
            content = (envelope.get("message") or {}).get("content") or []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text = (block.get("text") or "").strip()
                    return [RunEvent("message", text=text)] if text else []
                if btype == "tool_use":
                    tool = block.get("name", "")
                    call_id = block.get("id", "")
                    if call_id:
                        self._tool_names[call_id] = tool
                    kind = _TOOL_KIND.get(tool.lower(), "tool_output")
                    tool_input = block.get("input") or {}
                    meta = {"tool": tool, "status": "running", "call_id": call_id}
                    if tool.lower() in ("edit", "write"):
                        meta["file"] = tool_input.get("file_path", "")
                    if tool.lower() == "bash":
                        meta["command"] = tool_input.get("command", "")
                    return [RunEvent(kind, text="", meta=meta)]
            return []

        if etype == "user":
            content = (envelope.get("message") or {}).get("content") or []
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                call_id = block.get("tool_use_id", "")
                tool = self._tool_names.get(call_id, "")
                kind = _TOOL_KIND.get(tool.lower(), "tool_output")
                output = block.get("content", "")
                if not isinstance(output, str):
                    output = str(output)
                meta = {"tool": tool, "status": "completed", "call_id": call_id}
                if block.get("is_error"):
                    meta["is_error"] = True
                return [RunEvent(kind, text=output[:500], meta=meta)]
            return []

        if etype == "result":
            events: list[RunEvent] = []
            usage = envelope.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int) and (input_tokens or output_tokens):
                # provedor fixo (anthropic): esta CLI só fala o dialeto dela,
                # independente de system.provider (ver design.md D6/provisioning.py)
                events.append(RunEvent(
                    "usage",
                    meta={
                        "provider": "anthropic",
                        "model": system.get("model", ""),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                ))
            subtype = envelope.get("subtype")
            if subtype == "aborted":
                events.append(RunEvent("run_interrupted"))
            elif envelope.get("is_error"):
                events.append(RunEvent("run_error", text=envelope.get("result") or "erro desconhecido do provedor de LLM"))
            else:
                events.append(RunEvent("run_finished"))
            return events

        return []
