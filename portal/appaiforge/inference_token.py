"""Token opaco de inferência por sistema (etapa 3, ADR 0020).

O container do sistema carrega apenas este token; o broker troca pelo
credencial real no caminho de saída. Formato derivado (sem armazenar
plaintext, sem TTL — a validade é a versão vigente do sistema):

    <system_id>.<HMAC-SHA256(secret, "inference:" + system_id + ":" + version)>

Revogar o acesso de um sistema = incrementar `inference_token_version`; o
token antigo deixa de validar e o novo passa.
"""

import hashlib
import hmac

from .config import get_settings

_SEPARATOR = "."


def _secret(explicit: str | None = None) -> str:
    return explicit if explicit is not None else get_settings().secret_key


def _signature(system_id: str, version: int, secret: str) -> str:
    message = f"inference:{system_id}:{version}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def emit(system_id: str, version: int, secret: str | None = None) -> str:
    """Deriva o token opaco do sistema para a versão informada."""
    return f"{system_id}{_SEPARATOR}{_signature(system_id, version, _secret(secret))}"


def validate(token: str, version: int, secret: str | None = None) -> str | None:
    """Retorna o system_id se a assinatura conferir para a versão; None caso contrário."""
    if not token or _SEPARATOR not in token:
        return None
    system_id, signature = token.split(_SEPARATOR, 1)
    if not system_id or not signature:
        return None
    expected = _signature(system_id, version, _secret(secret))
    if hmac.compare_digest(signature, expected):
        return system_id
    return None


def token_for_system(system, secret: str | None = None) -> str:
    """Token do sistema a partir da versão persistida no próprio objeto."""
    return emit(system.id, system.inference_token_version, secret)


def rotate(system_id: str, secret: str | None = None) -> tuple[int, str]:
    """Incrementa a versão do sistema e devolve (nova_versao, novo_token).

    É a revogação: quem tiver o token da versão anterior deixa de validar.
    """
    from .db import session_scope
    from .models import System

    with session_scope() as s:
        system = s.get(System, system_id)
        if system is None:
            raise ValueError(f"sistema {system_id} não encontrado")
        system.inference_token_version = (system.inference_token_version or 0) + 1
        new_version = system.inference_token_version
    return new_version, emit(system_id, new_version, secret)
