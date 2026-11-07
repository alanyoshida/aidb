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


def compare_gate_decisions(args: argparse.Namespace) -> int:
    """Spike S5 (task 6.2, change db-proxy-gate-data-plane): compara o
    caminho antigo (globs) com o modo sombra do proxy no data plane."""
    from .gate_comparison import compare, format_report

    get_engine()
    report = compare(system_id=args.system_id, since_days=args.since_days, window_seconds=args.window_seconds)
    print(format_report(report))
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

    p_cmp = sub.add_parser(
        "compare-gate-decisions",
        help="spike S5: compara o gate por globs (antigo) com o modo sombra do proxy de banco",
    )
    p_cmp.add_argument("--system-id", default=None, help="restringe a um sistema; por padrão, todos")
    p_cmp.add_argument("--since-days", type=int, default=30, help="janela de dias pra trás (padrão 30)")
    p_cmp.add_argument("--window-seconds", type=float, default=30.0,
                       help="tolerância de tempo pra casar um registro antigo com um em sombra (padrão 30s)")
    p_cmp.set_defaults(func=compare_gate_decisions)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
