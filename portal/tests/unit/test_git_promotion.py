"""Promoção pela API do GitLab e teste do token (change add-system-git-remote, tarefa 8.1),
contra um servidor HTTP falso que imita a API."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from appaiforge import auth
from appaiforge.models import UserType
from appaiforge.services import git_remote

TOKEN = "tok-token-de-teste"


class FakeGitLab:
    def __init__(self):
        self.open_mrs: list[dict] = []
        self.created: list[dict] = []
        self.access_level = 30
        self.reject_token = False

        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                if fake.reject_token or self.headers.get("PRIVATE-TOKEN") != TOKEN:
                    self._send(401, {"message": "401 Unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path.startswith("/api/v4/projects/time%2Fapp/merge_requests"):
                    assert "source_branch=homolog" in self.path and "target_branch=main" in self.path
                    return self._send(200, fake.open_mrs)
                if self.path == "/api/v4/projects/time%2Fapp":
                    return self._send(200, {"path_with_namespace": "time/app",
                                            "permissions": {"project_access": {"access_level": fake.access_level},
                                                            "group_access": None}})
                self._send(404, {"message": "404"})

            def do_POST(self):
                if not self._auth():
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.created.append(body)
                mr = {"iid": 7, "web_url": "http://gitlab.test/time/app/-/merge_requests/7"}
                fake.open_mrs.append(mr)
                self._send(201, mr)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture()
def gitlab():
    fake = FakeGitLab()
    yield fake
    fake.server.shutdown()


@pytest.fixture()
def linked_system(clean_db, gitlab, monkeypatch):
    from appaiforge import git_sync
    from appaiforge.services.systems import create_system

    owner = auth.create_user("promo@t.local", "pw", UserType.editor.value)
    system = create_system(owner, "Promo", "promo-api")
    git_remote.configure(system, owner, url="git@gitlab.test:time/app.git", api_url=gitlab.url)
    git_sync._update_remote(system.id, enabled=True, host_key="ssh-ed25519 AAAA", state="synced")
    monkeypatch.setattr(git_sync, "_has_unsent", lambda system, branch: False)
    return owner, system


def test_sem_token_mostra_o_link_de_criacao(linked_system, gitlab):
    from appaiforge import git_sync

    owner, system = linked_system
    result = git_sync.request_promotion(system, owner)
    assert result["fallback"] and not gitlab.created
    assert result["url"].endswith("/time/app/-/merge_requests/new?merge_request%5Bsource_branch%5D=homolog"
                                  "&merge_request%5Btarget_branch%5D=main")


def test_com_token_abre_o_mr_e_depois_mostra_o_existente(linked_system, gitlab):
    from appaiforge import git_sync

    owner, system = linked_system
    git_remote.set_api_token(system, owner, TOKEN)
    first = git_sync.request_promotion(system, owner)
    assert first["created"] and first["url"].endswith("/merge_requests/7")
    assert gitlab.created[0]["source_branch"] == "homolog" and gitlab.created[0]["target_branch"] == "main"
    second = git_sync.request_promotion(system, owner)
    assert second["existing"] and second["url"] == first["url"]
    assert len(gitlab.created) == 1, "nenhum MR duplicado"
    assert git_remote.get_view(system)["last_mr_url"] == first["url"]


def test_token_recusado_cai_no_link(linked_system, gitlab):
    from appaiforge import git_sync

    owner, system = linked_system
    git_remote.set_api_token(system, owner, "tok-errado")
    result = git_sync.request_promotion(system, owner)
    assert result["fallback"] and "recusou" in result["message"]
    with pytest.raises(git_sync.RemoteError, match="recusou"):
        git_sync.check_api_token(system)


def test_teste_do_token_confere_permissao(linked_system, gitlab):
    from appaiforge import git_sync

    owner, system = linked_system
    git_remote.set_api_token(system, owner, TOKEN)
    assert "Token válido" in git_sync.check_api_token(system)
    gitlab.access_level = 20  # Reporter
    with pytest.raises(git_sync.RemoteError, match="Developer"):
        git_sync.check_api_token(system)
    assert not gitlab.created, "o teste não escreve nada"


@pytest.mark.parametrize("state, message", [("diverged", "divergência"), ("pending", "não enviados")])
def test_promocao_recusada_com_pendencia(linked_system, state, message):
    from appaiforge import git_sync

    owner, system = linked_system
    git_sync._update_remote(system.id, state=state)
    with pytest.raises(git_remote.InvalidRemote, match=message):
        git_sync.request_promotion(system, owner)


def test_api_inacessivel_vira_mensagem_com_o_endereco(linked_system, gitlab):
    """Piloto: com a URL da API errada (https://gitlab num GitLab só http), "Testar token" falhava
    sem nada na tela, porque o erro de conexão do httpx escapava do tratamento."""
    from appaiforge import git_sync

    owner, system = linked_system
    git_remote.configure(system, owner, url="git@gitlab.test:time/app.git", api_url="http://127.0.0.1:9")
    git_remote.set_api_token(system, owner, TOKEN)
    with pytest.raises(git_sync.RemoteError, match="inacessível em http://127.0.0.1:9") as exc:
        git_sync.check_api_token(system)
    assert exc.value.kind == "unreachable"
    with pytest.raises(git_sync.RemoteError, match="inacessível"):
        git_sync.request_promotion(system, owner)
