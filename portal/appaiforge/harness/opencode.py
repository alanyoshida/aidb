"""Adapter do harness opencode serve (ADR 0004; mapeamento do spike 5.1).

Endpoints usados (opencode 1.19.x):
- POST /session                       -> cria sessão
- POST /session/{id}/prompt_async     -> dispara prompt sem bloquear
- GET  /event                         -> SSE global (envelopes id/type/properties)
- POST /session/{id}/abort            -> interrompe
- GET  /session/{id}/diff             -> arquivos alterados na sessão

Cada sistema tem seu `opencode serve` na rede interna do Docker; o resolvedor
de base_url (injetado) devolve o endereço do container do sistema.
"""

import json
import threading
from typing import Callable

import httpx

from .base import HarnessPort, RunEvent

# portal provider -> providerID do catálogo (models.dev) e env de chave
PROVIDER_MAP = {
    "glm": ("zhipuai", "ZHIPU_API_KEY"),  # env esperada pelo catálogo (models.dev)
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("openai", "OPENAI_API_KEY"),
}

_TOOL_KIND = {
    "edit": "file_edited",
    "write": "file_edited",
    "bash": "command_run",
}


def opencode_provider(provider: str) -> tuple[str, str]:
    return PROVIDER_MAP.get(provider, (provider, f"{provider.upper()}_API_KEY"))


class OpencodeHarness(HarnessPort):
    def __init__(self, resolve_base_url: Callable[[dict], str], timeout: float = 30.0):
        self.resolve_base_url = resolve_base_url
        self.timeout = timeout
        self._aborting: set[str] = set()

    def create_session(self, system: dict) -> str:
        base = self.resolve_base_url(system)
        resp = httpx.post(f"{base}/session", json={"title": system.get("slug", "sistema")}, timeout=self.timeout)
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
        """Responde um permission.asked: approve -> 'once'; recusa -> 'reject'."""
        try:
            base = self.resolve_base_url(system)
            httpx.post(
                f"{base}/session/{session_id}/permission/{request_id}/reply",
                json={"response": "once" if approve else "reject"},
                timeout=self.timeout,
            )
        except httpx.HTTPError:
            pass

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started", meta={"session_id": session_id}))
        base = self.resolve_base_url(system)
        resp = httpx.post(
            f"{base}/session/{session_id}/prompt_async",
            json={"parts": [{"type": "text", "text": prompt}]},
            timeout=self.timeout,
        )
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
                    event = self._normalize(envelope, session_id)
                    if event is not None:
                        on_event(event)
                        if event.kind in ("run_finished", "run_error", "run_interrupted"):
                            return
        except httpx.HTTPError as exc:
            if session_id in self._aborting:
                on_event(RunEvent("run_interrupted"))
            else:
                on_event(RunEvent("run_error", text=f"falha de comunicação com o harness: {exc}"))
        finally:
            self._aborting.discard(session_id)

    @staticmethod
    def _token_count(value) -> int:
        """Uso de tokens vem em formatos diferentes por provedor (dict do
        opencode ou int direto de alguns provedores como o GLM)."""
        if isinstance(value, dict):
            value = value.get("tokens", 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _normalize(self, envelope: dict, session_id: str) -> RunEvent | None:
        etype = envelope.get("type")
        props = envelope.get("properties", {})
        if not isinstance(props, dict) or props.get("sessionID") != session_id:
            return None

        if etype == "message.updated":
            info = props.get("info") or {}
            if not isinstance(info, dict) or info.get("role") != "assistant":
                return None
            error = info.get("error")
            if isinstance(error, dict):
                error_data = error.get("data") or {}
                message = error_data.get("message") if isinstance(error_data, dict) else None
                return RunEvent("run_error", text=message or error.get("name") or "erro desconhecido do provedor de LLM")
            model = info.get("model") or {}
            tokens = info.get("tokens") or {}
            if isinstance(model, dict) and tokens:
                return RunEvent(
                    "usage",
                    meta={
                        "provider": model.get("providerID", ""),
                        "model": model.get("modelID", ""),
                        "input_tokens": self._token_count(tokens.get("input")),
                        "output_tokens": self._token_count(tokens.get("output")),
                    },
                )
            return None

        if etype == "message.part.updated":
            part = props.get("part", {})
            ptype = part.get("type")
            if ptype == "text":
                text = (part.get("text") or "").strip()
                if text:
                    return RunEvent("message", text=text)
            if ptype == "tool":
                tool = part.get("tool", "")
                state = part.get("state") or {}
                if not isinstance(state, dict):
                    state = {}
                kind = _TOOL_KIND.get(tool, "tool_output")
                meta = {"tool": tool}
                if tool in ("edit", "write"):
                    meta["file"] = (state.get("input") or {}).get("filePath", "")
                if tool == "bash":
                    meta["command"] = (state.get("input") or {}).get("command", "")
                return RunEvent(kind, text=str(state.get("output", ""))[:500], meta=meta)
            return None

        if etype == "session.status":
            status_info = props.get("status") or {}
            status = status_info.get("type") if isinstance(status_info, dict) else None
            if status == "idle":
                if session_id in self._aborting:
                    return RunEvent("run_interrupted")
                return RunEvent("run_finished")
            return None

        if etype == "session.diff":
            diff = props.get("diff") or []
            files = [d.get("file", "") for d in diff if isinstance(d, dict)] if isinstance(diff, list) else []
            if files:
                return RunEvent("file_edited", text=", ".join(files), meta={"files": files})
            return None

        if etype == "permission.asked":
            metadata = props.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            return RunEvent(
                "gate_request",
                text=str(metadata.get("command", "")),
                meta={
                    "request_id": props.get("id", ""),
                    "session_id": props.get("sessionID", ""),
                    "permission": props.get("permission", ""),
                },
            )

        return None

        return None
