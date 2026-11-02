"""Unitários da CLI: set-provider-key (chave cifrada em repouso, idempotente)."""

import pytest
from sqlalchemy import select

from appaiforge import cli
from appaiforge.db import session_scope
from appaiforge.models import ProviderKey
from appaiforge.security import decrypt_secret


def test_set_provider_key_cadastra_cifrado_e_atualiza(clean_db):
    rc = cli.main(["set-provider-key", "--provider", "glm", "--key", "chave-secreta-123"])
    assert rc == 0
    with session_scope() as s:
        row = s.execute(select(ProviderKey).where(ProviderKey.provider == "glm")).scalar_one()
        stored = row.key_encrypted
    assert "chave-secreta-123" not in stored  # cifrada em repouso
    assert decrypt_secret(stored) == "chave-secreta-123"

    # segunda execução atualiza em vez de duplicar
    rc = cli.main(["set-provider-key", "--provider", "glm", "--key", "outra-chave"])
    assert rc == 0
    with session_scope() as s:
        rows = s.execute(select(ProviderKey).where(ProviderKey.provider == "glm")).scalars().all()
        assert len(rows) == 1
        assert decrypt_secret(rows[0].key_encrypted) == "outra-chave"
