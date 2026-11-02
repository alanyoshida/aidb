"""Steps BDD de system-management: slug, provedor padrão e troca de provedor."""

from pytest_bdd import given, parsers, scenarios, then, when

from appaiforge import auth
from appaiforge.services.systems import SlugTaken, create_system, get_system, set_provider

scenarios("features/system_management.feature")

_ctx: dict = {}


def _editor(email: str):
    return auth.create_user(email, "pw", "editor")


@given(parsers.parse('um editor autenticado com o sistema "{slug}" criado'))
def editor_com_sistema(clean_db, slug):
    editor = _editor(f"{slug}-owner@sys.local")
    _ctx["user"] = editor
    _ctx[slug] = create_system(editor, slug.upper(), slug)


@given("um editor autenticado sem sistema criado")
def editor_sem_sistema(clean_db):
    _ctx["user"] = _editor("fresh@sys.local")


@when(parsers.parse('ele cria um sistema com nome "{name}" e slug "{slug}"'))
def cria_sistema(name, slug):
    try:
        _ctx["system"] = create_system(_ctx["user"], name, slug)
        _ctx["erro"] = None
    except SlugTaken:
        _ctx["system"] = None
        _ctx["erro"] = "slug_taken"


@when(parsers.parse('ele cria um sistema com nome "{name}" e slug "{slug}" sem informar provedor'))
def cria_sistema_sem_provedor(name, slug):
    _ctx["system"] = create_system(_ctx["user"], name, slug)


@then("a criação é recusada por slug já existente")
def slug_recusado():
    assert _ctx["erro"] == "slug_taken"
    assert _ctx["system"] is None


@then(parsers.parse('o sistema usa o provedor "{provider}" com o modelo padrão'))
def provedor_padrao(provider):
    assert _ctx["system"].provider == provider
    assert _ctx["system"].model  # modelo padrão preenchido


@when(parsers.parse('ele altera o provedor do sistema para "{provider}"'))
def altera_provedor(provider):
    set_provider(_ctx["erp"].id, provider, f"{provider}-model-x")


@then(parsers.parse('o sistema passa a usar o provedor "{provider}"'))
def verifica_provedor(provider):
    system = get_system(_ctx["erp"].id)  # recarrega do banco (objeto do given está expungado)
    assert system.provider == provider
