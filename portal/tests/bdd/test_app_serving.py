"""Steps BDD de app-serving: propagação de identidade via token HMAC (spec app-serving).

Exercita o template canônico que as guidelines mandam copiar para a app gerada
(appaiforge.app_template.identity) — comportamento observável da app.
"""

import time

from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge.app_template.identity import resolve_identity
from appaiforge.security import generate_secret, sign_identity_token

scenarios("features/app_serving.feature")

_ctx: dict = {}


@given("um sistema com segredo de identidade")
def sistema_com_segredo(clean_db):
    _ctx["secret"] = generate_secret()


@when(parsers.parse('o portal assina um token para o usuário "{user_id}" do tipo "{user_type}"'))
def portal_assina(user_id, user_type):
    token = sign_identity_token(_ctx["secret"], {"user_id": user_id, "user_type": user_type}, ttl_seconds=60)
    _ctx["payload"] = resolve_identity(_ctx["secret"], token)


@then(parsers.parse('a app reconhece "{user_id}" como "{user_type}" pelo token'))
def app_reconhece(user_id, user_type):
    assert _ctx["payload"] is not None
    assert _ctx["payload"]["user_id"] == user_id
    assert _ctx["payload"]["user_type"] == user_type


@when("a app recebe um token assinado com segredo errado")
def token_segredo_errado():
    from appaiforge.security import sign_identity_token as sign

    token = sign("segredo-errado", {"user_id": "u1", "user_type": "app_user"}, ttl_seconds=60)
    _ctx["payload"] = resolve_identity(_ctx["secret"], token)


@then("a app recusa a sessão")
def app_recusa():
    assert _ctx["payload"] is None


@when("a app recebe um token válido emitido há mais de uma hora")
def token_expirado():
    token = sign_identity_token(_ctx["secret"], {"user_id": "u1", "user_type": "app_user"}, ttl_seconds=-3600)
    _ctx["payload"] = resolve_identity(_ctx["secret"], token)
    assert time.time() > 0
