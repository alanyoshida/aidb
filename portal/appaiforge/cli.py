"""CLI do portal: bootstrap do admin e chaves de provedor LLM (tasks 1.4, ADR 0012)."""

import argparse
import sys

from .auth import create_user
from .db import get_engine
from .models import Base


def create_admin(args: argparse.Namespace) -> int:
    get_engine()
    Base.metadata.create_all(get_engine())  # idempotente; Alembic é o caminho normal
    user = create_user(args.email, args.password, "admin")
    print(f"admin criado: {user.email} ({user.id})")
    return 0


def set_provider_key(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from .db import session_scope
    from .models import ProviderKey
    from .security import encrypt_secret

    get_engine()
    with session_scope() as s:
        exists = s.execute(select(ProviderKey).where(ProviderKey.provider == args.provider)).scalar_one_or_none()
        if exists is not None:
            exists.key_encrypted = encrypt_secret(args.key)
            print(f"chave do provedor '{args.provider}' atualizada")
        else:
            s.add(ProviderKey(provider=args.provider, key_encrypted=encrypt_secret(args.key)))
            print(f"chave do provedor '{args.provider}' cadastrada")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="appaiforge")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="cria o usuário admin inicial")
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--password", required=True)
    p_admin.set_defaults(func=create_admin)

    p_key = sub.add_parser("set-provider-key", help="cadastra/atualiza a chave de um provedor de LLM (glm, anthropic, openai)")
    p_key.add_argument("--provider", required=True, help="id do provedor no portal (ex.: glm)")
    p_key.add_argument("--key", required=True, help="a chave de API (será armazenada cifrada)")
    p_key.set_defaults(func=set_provider_key)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
