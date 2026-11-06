"""Registro idempotente do uso de tokens/custo vindo do LiteLLM (etapa 3, ADR 0020).

O broker injeta `metadata` (system_id, run_id, chat_session_id) no corpo; o
callback do LiteLLM envia o evento para `/internal/inference/usage`, que grava
`TokenUsage` uma única vez por id de evento.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import session_scope
from ..models import TokenUsage


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract(payload: dict) -> dict | None:
    std = payload.get("standard_logging_object") or payload
    metadata = std.get("metadata") or payload.get("metadata") or {}
    external_id = (
        std.get("id") or payload.get("id")
        or std.get("litellm_call_id") or payload.get("litellm_call_id")
    )
    run_id = metadata.get("run_id")
    system_id = metadata.get("system_id")
    if not external_id or not run_id or not system_id:
        return None
    usage = std.get("usage") or payload.get("usage") or {}
    input_tokens = _as_int(usage.get("prompt_tokens", usage.get("input_tokens")))
    output_tokens = _as_int(usage.get("completion_tokens", usage.get("output_tokens")))
    model = std.get("model") or payload.get("model") or ""
    provider = std.get("custom_llm_provider") or metadata.get("provider") or ""
    try:
        cost = float(std.get("response_cost") or payload.get("response_cost") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return {
        "external_id": str(external_id),
        "run_id": str(run_id),
        "system_id": str(system_id),
        "provider": str(provider),
        "model": str(model),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }


def record_usage(payload: dict) -> bool:
    """Grava o uso uma única vez por evento; devolve True se inseriu."""
    data = _extract(payload)
    if data is None:
        return False
    with session_scope() as s:
        existing = s.execute(
            select(TokenUsage.id).where(TokenUsage.external_id == data["external_id"])
        ).scalar_one_or_none()
        if existing is not None:
            return False
        s.add(TokenUsage(**data))
        try:
            s.flush()
        except IntegrityError:
            # corrida entre callbacks do mesmo evento: já registrado por outro
            s.rollback()
            return False
    return True
