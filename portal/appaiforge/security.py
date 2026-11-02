"""Primitivas de segurança: hash de senha (scrypt), cifra de segredos (Fernet)
e token de identidade HMAC para as apps geradas (ADR 0006, 0007)."""

import base64
import hashlib
import hmac
import json
import os
import time

from cryptography.fernet import Fernet, InvalidToken

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def _fernet() -> Fernet:
    secret = __import__("appaiforge.config", fromlist=["get_settings"]).get_settings().secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def generate_secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def sign_identity_token(secret: str, payload: dict, ttl_seconds: int) -> str:
    """Token curto HMAC-SHA256 (payload.payload_signature, base64url)."""
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_seconds
    body_b64 = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=")
    sig = hmac.new(secret.encode(), body_b64, hashlib.sha256).hexdigest()
    return f"{body_b64.decode()}.{sig}"


def verify_identity_token(secret: str, token: str) -> dict | None:
    """Retorna o payload se o token for válido e não expirado; None caso contrário."""
    try:
        body_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), body_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
