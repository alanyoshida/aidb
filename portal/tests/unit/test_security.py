"""Unitários de segurança: hash de senha, cifra e token HMAC (ADR 0006/0007)."""

import time

from appaiforge.security import (
    decrypt_secret,
    encrypt_secret,
    generate_secret,
    hash_password,
    sign_identity_token,
    verify_identity_token,
    verify_password,
)


def test_senha_nao_fica_em_texto_puro():
    stored = hash_password("minha-senha")
    assert "minha-senha" not in stored
    assert stored.startswith("scrypt$")


def test_verifica_senha_correta_e_recusa_errada():
    stored = hash_password("minha-senha")
    assert verify_password("minha-senha", stored)
    assert not verify_password("outra-senha", stored)
    assert not verify_password("minha-senha", "lixo")


def test_cifra_segredo_e_nao_o_expos():
    ciphertext = encrypt_secret("senha-do-banco")
    assert "senha-do-banco" not in ciphertext
    assert decrypt_secret(ciphertext) == "senha-do-banco"


def test_token_identidade_valido():
    secret = generate_secret()
    token = sign_identity_token(secret, {"user_id": "u1", "user_type": "app_user"}, ttl_seconds=60)
    payload = verify_identity_token(secret, token)
    assert payload is not None
    assert payload["user_id"] == "u1"


def test_token_identidade_rejeita_assinatura_falsificada():
    secret = generate_secret()
    token = sign_identity_token(secret, {"user_id": "u1"}, ttl_seconds=60)
    assert verify_identity_token(generate_secret(), token) is None
    assert verify_identity_token(secret, token + "x") is None


def test_token_identidade_rejeita_expirado():
    secret = generate_secret()
    token = sign_identity_token(secret, {"user_id": "u1"}, ttl_seconds=-1)
    assert verify_identity_token(secret, token) is None
    assert time.time() > 0
