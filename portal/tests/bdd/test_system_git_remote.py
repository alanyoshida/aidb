"""Steps BDD de system-git-remote (change add-system-git-remote), driver Docker, contra o servidor
git por SSH efêmero dos testes de integração."""

import json
import os
import sys

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "integration"))

from appaiforge import auth, checkpoints, git_sync  # noqa: E402
from appaiforge.services import git_remote  # noqa: E402

scenarios("features/system_git_remote.feature")

_ctx: dict = {}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for var, sub in (("APPAIFORGE_WORKSPACES_DIR", "workspaces"), ("APPAIFORGE_GITDIRS_DIR", "gitdirs"),
                     ("APPAIFORGE_GIT_RELAYS_DIR", "relays"), ("APPAIFORGE_DYNAMIC_CONFIG_DIR", "dynamic"),
                     ("APPAIFORGE_CONFIGS_DIR", "configs")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", "docker")
    from appaiforge.config import get_settings

    get_settings.cache_clear()
    _ctx.clear()
    yield tmp_path
    server = _ctx.get("server")
    if server is not None:
        server.container.remove(force=True)


def _server():
    if "server" not in _ctx:
        from git_ssh_server import start_server

        _ctx["server"] = start_server(str(_ctx["tmp"] / "git-ssh"))
    return _ctx["server"]


def _write(name: str, content: str) -> None:
    path = os.path.join(checkpoints.workspace_dir(_ctx["system"]), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _read(name: str):
    path = os.path.join(checkpoints.workspace_dir(_ctx["system"]), name)
    return open(path).read() if os.path.exists(path) else None


def _new_system(slug: str):
    from appaiforge.services.systems import create_system

    owner = auth.create_user(f"{slug}@bdd.local", "pw", "editor")
    return owner, create_system(owner, slug, slug)


@given("um sistema com um checkpoint")
def sistema_com_checkpoint(env, clean_db):
    _ctx["tmp"] = env
    _ctx["owner"], _ctx["system"] = _new_system(f"bdd-git-{os.urandom(3).hex()}")
    _write("app/main.py", "linha 1\nlinha 2\nlinha 3\n")
    checkpoints.record_checkpoint(_ctx["system"], None, "inicial", _ctx["owner"])


@given("um sistema com um checkpoint e o repositório configurado")
def sistema_configurado(env, clean_db):
    sistema_com_checkpoint(env, clean_db)
    server = _server()
    view = git_remote.configure(_ctx["system"], _ctx["owner"], url=server.url)
    server.authorize(view["public_key"])
    git_remote.confirm_host_key(_ctx["system"], _ctx["owner"],
                                git_sync.scan_host_key(git_remote.parse_remote_url(view["url"])).key)


@given("um sistema vinculado ao repositório remoto")
def sistema_vinculado(env, clean_db):
    sistema_configurado(env, clean_db)
    git_sync.activate(_ctx["system"], _ctx["owner"])


@given("dois sistemas com repositório configurado")
def dois_sistemas(env, clean_db):
    _ctx["keys"] = []
    for _ in range(2):
        owner, system = _new_system(f"bdd-dois-{os.urandom(3).hex()}")
        _ctx["keys"].append(git_remote.configure(system, owner, url="git@h:a/b.git")["public_key"])


@when("o editor informa apenas o endereço do repositório")
def informa_endereco():
    _ctx["view"] = git_remote.configure(_ctx["system"], _ctx["owner"], url="git@gitlab.exemplo.com:time/app.git")


@when(parsers.parse('o editor informa o endereço "{url}"'))
def informa_endereco_invalido(url):
    try:
        git_remote.configure(_ctx["system"], _ctx["owner"], url=url)
        _ctx["error"] = None
    except git_remote.InvalidRemote as exc:
        _ctx["error"] = str(exc)


@when(parsers.parse('o editor informa o endereço "{url}" sem endereço de API'))
def informa_sem_api(url):
    _ctx["view"] = git_remote.configure(_ctx["system"], _ctx["owner"], url=url)


@then(parsers.parse('a branch de trabalho fica "{working}" e a de destino fica "{target}"'))
def branches_padrao(working, target):
    assert (_ctx["view"]["working_branch"], _ctx["view"]["target_branch"]) == (working, target)


@then("a configuração é recusada explicando o formato aceito")
def recusada():
    assert _ctx["error"] and "ssh://" in _ctx["error"]


@then("cada um tem uma chave pública diferente")
def chaves_diferentes():
    assert _ctx["keys"][0] != _ctx["keys"][1]


@then("nenhuma resposta nem registro de auditoria contém a chave privada")
def chave_privada_nunca_exibida():
    from sqlalchemy import select

    from appaiforge.db import session_scope
    from appaiforge.models import ManagementAudit

    secret = git_remote.load_secrets(_ctx["system"].id).private_key.splitlines()[1]
    assert secret not in json.dumps(git_remote.get_view(_ctx["system"]))
    with session_scope() as s:
        rows = s.execute(select(ManagementAudit)).scalars().all()
        assert secret not in json.dumps([r.details for r in rows])


@then(parsers.parse('o endereço da API usado é "{url}"'))
def api_derivada(url):
    assert _ctx["view"]["effective_api_url"] == url


@when("o servidor passa a apresentar outra chave")
def servidor_troca_chave():
    _server().rotate_host_keys()
    _write("app/main.py", "linha 1\nmudou\nlinha 3\n")
    checkpoints.record_checkpoint(_ctx["system"], None, "depois da troca", _ctx["owner"])
    _ctx["result"] = git_sync.push_now(_ctx["system"], _ctx["owner"])


@then("o envio é recusado porque a identidade do servidor mudou")
def recusado_por_identidade():
    assert _ctx["result"]["kind"] == "host_key_changed"
    assert git_remote.get_view(_ctx["system"])["state"] == "error"


@when("o editor ativa o vínculo")
def ativa():
    git_sync.activate(_ctx["system"], _ctx["owner"])


@then("a branch de trabalho é criada no remoto com os checkpoints do sistema")
def branch_criada():
    assert _server().git("rev-parse", "homolog") == checkpoints._git(_ctx["system"], "rev-parse", "HEAD")


@given("a branch de trabalho do remoto tem histórico próprio")
def historico_proprio():
    _server().init_repo(with_branches=("main", "homolog"))
    _ctx["remote_before"] = _server().git("rev-parse", "homolog")


@when("o editor tenta ativar o vínculo")
def tenta_ativar():
    try:
        git_sync.activate(_ctx["system"], _ctx["owner"])
        _ctx["error"] = None
    except git_sync.UnrelatedHistory as exc:
        _ctx["error"] = exc


@then("o vínculo é recusado e o remoto não muda")
def vinculo_recusado():
    assert _ctx["error"] is not None
    assert git_remote.get_view(_ctx["system"])["enabled"] is False
    assert _server().git("rev-parse", "homolog") == _ctx["remote_before"]


@when("um novo checkpoint do editor é criado")
def novo_checkpoint():
    _write("app/main.py", "linha 1\npelo chat\nlinha 3\n")
    checkpoints.record_checkpoint(_ctx["system"], None, "pelo chat", _ctx["owner"])
    git_sync.after_checkpoint(_ctx["system"], _ctx["owner"])


@then("o commit aparece na branch de trabalho do remoto com o editor como autor")
def commit_no_remoto():
    assert _server().git("log", "-1", "--format=%ae", "homolog") == _ctx["owner"].email


@when("um novo checkpoint é criado com o remoto fora do ar")
def checkpoint_remoto_fora():
    _server().stop()
    try:
        novo_checkpoint()
    finally:
        _server().start()


@then("o checkpoint existe e o repositório fica com envio pendente")
def envio_pendente():
    assert checkpoints.list_checkpoints(_ctx["system"])[0]["message"] == "pelo chat"
    assert git_remote.get_view(_ctx["system"])["state"] == "pending"


@given("um merge request humano foi mergeado na branch de trabalho")
def merge_humano():
    _server().commit_as_human("homolog", {"humano.txt": "do merge request\n"}, "merge humano")


@given("o workspace tem alterações sem checkpoint")
def alteracoes_sem_checkpoint():
    _write("app/rascunho.py", "sobras\n")


@when("o portal sincroniza antes de uma execução")
def sincroniza_antes():
    _ctx["blocked"] = git_sync.before_run(_ctx["system"], _ctx["owner"])


@then("o workspace contém as alterações mergeadas")
def contem_mergeado():
    assert _ctx["blocked"] is None and _read("humano.txt") == "do merge request\n"


@then("o histórico mostra um checkpoint vindo do repositório remoto")
def checkpoint_remoto():
    assert checkpoints.list_checkpoints(_ctx["system"])[0]["origin"] == "remote"


@then("a execução é impedida pedindo para salvar ou descartar as alterações")
def execucao_impedida():
    assert _ctx["blocked"] and "salve ou descarte" in _ctx["blocked"]
    assert _read("humano.txt") is None


@given("o remoto e o sistema alteraram a mesma linha")
def mesma_linha():
    _server().commit_as_human("homolog", {"app/main.py": "linha 1\nREMOTO\nlinha 3\n"}, "merge humano")
    _write("app/main.py", "linha 1\nLOCAL\nlinha 3\n")
    checkpoints.record_checkpoint(_ctx["system"], None, "local", _ctx["owner"])
    git_sync.after_checkpoint(_ctx["system"], _ctx["owner"])


@then("o sistema fica divergente com o arquivo em conflito listado")
def divergente():
    view = git_remote.get_view(_ctx["system"])
    assert view["state"] == "diverged" and view["conflict_files"] == ["app/main.py"]


@then("o workspace não contém marcas de conflito")
def sem_marcas():
    assert "<<<<<<<" not in _read("app/main.py")


@when("o editor adota a versão do remoto")
def adota():
    git_sync.adopt_remote(_ctx["system"], _ctx["owner"])


@then("o workspace tem o conteúdo do remoto e o sistema deixa de estar divergente")
def adotado():
    assert _read("app/main.py") == "linha 1\nREMOTO\nlinha 3\n"
    assert git_remote.get_view(_ctx["system"])["state"] == "synced"


@when("o editor solicita promoção")
def solicita_promocao():
    try:
        git_sync.request_promotion(_ctx["system"], _ctx["owner"])
        _ctx["error"] = None
    except git_remote.InvalidRemote as exc:
        _ctx["error"] = str(exc)


@then("a solicitação é recusada explicando o que resolver")
def promocao_recusada():
    assert _ctx["error"] and "divergência" in _ctx["error"]


@when(parsers.parse('o agente cria "{name}" e um checkpoint é criado'))
def agente_cria_pipeline(name):
    _write(name, "job: {script: [curl evil]}\n")
    novo_checkpoint()


@then("o arquivo de pipeline não chega ao remoto")
def pipeline_fora():
    assert ".gitlab-ci.yml" not in _server().git("ls-tree", "--name-only", "homolog").split()


@when("o editor desativa o vínculo e um novo checkpoint é criado")
def desativa():
    _ctx["remote_before"] = _server().git("rev-parse", "homolog")
    git_remote.set_enabled(_ctx["system"], _ctx["owner"], False)
    novo_checkpoint()


@then("nada novo chega ao remoto")
def nada_novo():
    assert _server().git("rev-parse", "homolog") == _ctx["remote_before"]


# --- Manifesto de conexões pelo alias (change add-db-manager-role) ---

def _grant(alias: str, kind: str, active: bool) -> None:
    from appaiforge.db import session_scope
    from appaiforge.models import DbConnection, DbConnectionGrant

    with session_scope() as s:
        conn = DbConnection(name=f"Catálogo {alias}", kind=kind, host="db.interno", port=5432,
                            database="base_secreta", username="usuario_secreto", password_encrypted="cifrado")
        s.add(conn)
        s.flush()
        s.add(DbConnectionGrant(connection_id=conn.id, system_id=_ctx["system"].id, max_mode="read_write",
                                mode="read_write", active=active, alias=alias if active else None,
                                alias_key=alias.upper() if active else None))


@given(parsers.parse('as conexões ativas "{a}" ({kind_a}) e "{b}" ({kind_b}) no sistema'))
def conexoes_ativas(a, kind_a, b, kind_b):
    _grant(a, kind_a, True)
    _grant(b, kind_b, True)


@given(parsers.parse('a conexão "{alias}" autorizada e não ativada no sistema'))
def conexao_nao_ativada(alias):
    _grant(alias, "postgres", False)


@when("um checkpoint é criado com o manifesto de conexões")
def checkpoint_com_manifesto():
    novo_checkpoint()


def _remote_manifest() -> str:
    return _server().git("show", "homolog:.aidb/manifest.json")


@then(parsers.parse('o manifesto no remoto lista "{a}" ({kind_a}) e "{b}" ({kind_b})'))
def manifesto_lista(a, kind_a, b, kind_b):
    assert json.loads(_remote_manifest())["connections"] == [
        {"name": a, "kind": kind_a}, {"name": b, "kind": kind_b},
    ]


@then("o manifesto no remoto não tem endereço, usuário nem nome do catálogo")
def manifesto_sem_segredo():
    raw = _remote_manifest()
    for secret in ("db.interno", "5432", "base_secreta", "usuario_secreto", "cifrado", "Catálogo"):
        assert secret not in raw
