"""Fronteira do harness (ADR 0004): interface + eventos normalizados.

O portal fala apenas com HarnessPort; implementações: OpencodeHarness (real),
FakeHarness (E2E determinístico). Eventos são dataclasses simples consumidos
pela fila e pelo chat.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunEvent:
    kind: str  # run_started | message | file_edited | command_run | tool_output | usage | run_finished | run_error | run_interrupted
    text: str = ""
    meta: dict = field(default_factory=dict)
    # espelha RunEventRecord.created_at: o chat mostra o horário também durante a
    # execução, antes de o evento ser persistido
    created_at: datetime = field(default_factory=_now)


EventCallback = Callable[[RunEvent], None]


class SessionExpiredError(Exception):
    """Sessão do harness não existe mais (container recriado ou processo morto)."""


class HarnessPort:
    """Contrato do portal para dirigir um agente de código por sistema."""

    def create_session(self, system: dict) -> str:
        raise NotImplementedError

    def run(self, system: dict, session_id: str, prompt: str, on_event: EventCallback) -> None:
        """Executa um prompt; emite eventos via on_event até terminar/interrar.

        Bloqueia a thread chamadora (worker da fila).
        """
        raise NotImplementedError

    def interrupt(self, system: dict, session_id: str) -> None:
        raise NotImplementedError

    def reply_gate(self, system: dict, session_id: str, request_id: str, approve: bool) -> None:
        """Responde um pedido de permissão do gate (spec destructive-gate)."""
        raise NotImplementedError
