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
import logging
import threading
from typing import Callable

import httpx

from .base import HarnessPort, RunEvent, SessionExpiredError

log = logging.getLogger(__name__)

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
        # messageID -> role ("user"/"assistant"), populado por `message.updated` —
        # `message.part.updated` não carrega role nenhum, só `messageID` (ver abaixo)
        self._message_roles: dict[str, str] = {}
        # sessionID -> texto do prompt em andamento, usado como critério de
        # desempate quando a parte de texto chega antes do `message.updated`
        # que diria o role (achado ao vivo: respostas curtas/rápidas do
        # modelo — poucos tokens de saída — às vezes streamam a parte de
        # texto antes do evento que anuncia a mensagem; tratar "role ainda
        # desconhecido" como "esconder" fazia a resposta real sumir do chat)
        self._pending_prompt: dict[str, str] = {}

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
        """Responde um permission.asked: approve -> 'once'; recusa -> 'reject'.

        opencode 1.19.x: POST /session/{sessionID}/permissions/{permissionID}
        com corpo {"response": ...}. (A rota antiga .../permission/{id}/reply
        não aplica a resposta e deixava a execução presa.)
        """
        try:
            base = self.resolve_base_url(system)
            resp = httpx.post(
                f"{base}/session/{session_id}/permissions/{request_id}",
                json={"response": "once" if approve else "reject"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("falha ao responder permissão do gate (%s): %s", request_id, exc)

    def reply_question(self, system: dict, session_id: str, request_id: str, label: str) -> None:
        """Responde a ferramenta nativa `question` do opencode (distinta do
        permission.asked acima — o próprio agente decide perguntar, não é o
        gate de permissão): POST /question/{requestID}/reply, corpo
        {"answers": [[rótulo]]} — só a primeira pergunta do pedido é
        suportada (ver achado real no design da task)."""
        try:
            base = self.resolve_base_url(system)
            resp = httpx.post(
                f"{base}/question/{request_id}/reply",
                json={"answers": [[label]]},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("falha ao responder pergunta do agente (%s): %s", request_id, exc)

    def reject_question(self, system: dict, session_id: str, request_id: str) -> None:
        try:
            base = self.resolve_base_url(system)
            resp = httpx.post(f"{base}/question/{request_id}/reject", timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("falha ao rejeitar pergunta do agente (%s): %s", request_id, exc)

    def run(self, system: dict, session_id: str, prompt: str, on_event) -> None:
        on_event(RunEvent("run_started", meta={"session_id": session_id}))
        base = self.resolve_base_url(system)
        # Sem o modelo explícito o opencode cai no default dele, que é escolhido
        # pelo catálogo e pode nem servir para chat (já veio um de imagem),
        # respondendo sem nenhum texto. O provedor/modelo do sistema manda.
        provider_id, _ = opencode_provider(system.get("provider", ""))
        payload: dict = {"parts": [{"type": "text", "text": prompt}]}
        if provider_id and system.get("model"):
            payload["model"] = {"providerID": provider_id, "modelID": system["model"]}
        resp = httpx.post(
            f"{base}/session/{session_id}/prompt_async",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise SessionExpiredError(f"sessão opencode {session_id!r} não existe mais")
        resp.raise_for_status()

        self._pending_prompt[session_id] = prompt.strip()
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
            self._pending_prompt.pop(session_id, None)

    def _normalize(self, envelope: dict, session_id: str) -> RunEvent | None:
        etype = envelope.get("type")
        props = envelope.get("properties", {})
        if not isinstance(props, dict) or props.get("sessionID") != session_id:
            return None

        if etype == "message.updated":
            info = props.get("info") or {}
            if not isinstance(info, dict):
                return None
            message_id = info.get("id")
            role = info.get("role")
            if message_id and role:
                self._message_roles[message_id] = role
            if role != "assistant":
                return None
            error = info.get("error")
            if isinstance(error, dict):
                error_data = error.get("data") or {}
                message = error_data.get("message") if isinstance(error_data, dict) else None
                return RunEvent("run_error", text=message or error.get("name") or "erro desconhecido do provedor de LLM")
            model = info.get("model") or {}
            tokens = info.get("tokens") or {}
            # Uso normalizado vem do callback do LiteLLM via broker (D6); o
            # evento do harness só é emitido quando ele já traz inteiros.
            input_tokens = tokens.get("input")
            output_tokens = tokens.get("output")
            if isinstance(model, dict) and isinstance(input_tokens, int) and isinstance(output_tokens, int):
                return RunEvent(
                    "usage",
                    meta={
                        "provider": model.get("providerID", ""),
                        "model": model.get("modelID", ""),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                )
            return None

        if etype == "message.part.updated":
            part = props.get("part", {})
            ptype = part.get("type")
            if ptype == "text":
                text = (part.get("text") or "").strip()
                if not text:
                    return None
                # a parte não carrega role nenhum (só `messageID`) — sem checar o
                # role da mensagem dona, a própria pergunta do editor (parte da
                # mensagem dele, role "user") também vira um RunEvent "message",
                # e o chat a renderiza como se fosse resposta do agente
                role = self._message_roles.get(part.get("messageID"))
                if role == "user":
                    return None
                if role is None and text == self._pending_prompt.get(session_id):
                    # `message.updated` (que diria o role) ainda não chegou —
                    # texto idêntico ao prompt recém-enviado é o eco da
                    # própria mensagem do editor, não resposta do agente.
                    # Qualquer outro texto nessa mesma situação é tratado
                    # como resposta (único outro role possível no schema do
                    # opencode é "assistant") — não "esconder por via das
                    # dúvidas", que apagava respostas curtas de verdade.
                    return None
                return RunEvent("message", text=text)
            if ptype == "tool":
                tool = part.get("tool", "")
                state = part.get("state") or {}
                if not isinstance(state, dict):
                    state = {}
                kind = _TOOL_KIND.get(tool, "tool_output")
                # "status" (pending/running/completed) só preenche de verdade quando a
                # ferramenta termina; usado pelo chat pra não mostrar o mesmo comando como
                # "executando" e "concluído" com texto idêntico (achado ao vivo: duas linhas
                # iguais no log de debug — o comando ainda rodando e o comando pronto são
                # eventos legitimamente diferentes, mas pareciam duplicados)
                meta = {"tool": tool, "status": state.get("status", "")}
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
            command = str(metadata.get("command", ""))
            return RunEvent(
                "gate_request",
                text=command,
                meta={
                    "request_id": props.get("id", ""),
                    "session_id": props.get("sessionID", ""),
                    # "bash" é o único tipo que o gate de SQL sabe classificar (ADR 0017);
                    # opencode também pede permissão para outras coisas (ex.: acesso a
                    # diretório fora do workspace) — o portal trata isso à parte,
                    # nunca como se fosse uma operação de banco.
                    "permission": props.get("permission", ""),
                    "command": command,
                },
            )

        if etype == "question.asked":
            questions = props.get("questions") or []
            if not isinstance(questions, list) or not questions:
                return None
            # só a primeira pergunta do pedido é suportada — a ferramenta
            # permite várias, mas o card do chat (task) só sabe mostrar uma
            q = questions[0] if isinstance(questions[0], dict) else {}
            options = q.get("options") or []
            labels = [o.get("label", "") for o in options if isinstance(o, dict)]
            return RunEvent(
                "question_asked",
                text=q.get("question", ""),
                meta={
                    "request_id": props.get("id", ""),
                    "header": q.get("header", ""),
                    "options": labels,
                },
            )

        return None
