"""E2E com GitLab local: promoção por merge request, pipeline e tag; promoção sem token; chave só
leitura (change add-system-git-remote, tarefa 9.1)."""

import uuid

import pytest

import gitlab
from test_repository_link import _send, _wait_badge
from test_repository_sync import _linked_system

pytestmark = pytest.mark.e2e


def test_promocao_merge_e_tag_da_versao(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    pid = project["id"]
    try:
        _send(page, "anote mudança para promover")
        page.locator('[data-testid=tab-repository]').click()
        _wait_badge(page, "sincronizado")

        # token de projeto (Developer, api), testado pela aba
        page.locator('[data-testid=repo-token]').fill(gitlab.project_token(pid))
        page.locator('[data-testid=repo-token-save]').click()
        page.get_by_text("Token cadastrado").wait_for(timeout=15_000)
        page.locator('[data-testid=repo-token-test]').click()
        page.get_by_text("Token válido").wait_for(timeout=30_000)

        # solicitar promoção abre o MR; de novo, mostra o mesmo
        page.locator('[data-testid=repo-promote]').click()
        page.get_by_text("Merge request aberto").wait_for(timeout=30_000)
        mrs = gitlab.open_mrs(pid)
        assert len(mrs) == 1
        url = page.locator('[data-testid=repo-mr-url]').inner_text().strip()
        assert url == mrs[0]["web_url"]
        page.locator('[data-testid=repo-promote]').click()
        page.get_by_text("Já existe um merge request aberto").wait_for(timeout=30_000)
        assert len(gitlab.open_mrs(pid)) == 1, "nenhum MR duplicado"

        # pipeline de validação verde, merge pelo humano e tag criada pelo pipeline da main
        merged = gitlab.merge_when_green(pid, mrs[0]["iid"])
        assert merged["state"] == "merged"
        tag = gitlab.wait_tag(pid)
        assert tag["name"].startswith("v1.0.")
        assert tag["commit"]["id"] == gitlab.branch(pid, "main")["commit"]["id"]

        # sem token, a promoção só mostra o link de criação
        page.locator('[data-testid=repo-token-remove]').click()
        page.get_by_text("Token removido").wait_for(timeout=15_000)
        page.locator('[data-testid=repo-promote]').click()
        page.get_by_text("Sem token de API").wait_for(timeout=30_000)
        link = page.locator('[data-testid=repo-mr-url]').inner_text().strip()
        assert "/-/merge_requests/new?" in link and "source_branch%5D=homolog" in link
        assert gitlab.open_mrs(pid) == []
    finally:
        gitlab.delete_project(pid)


def test_chave_somente_leitura_e_recusada_no_envio(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    pid = project["id"]
    try:
        # troca a chave de implantação por uma só de leitura
        for key in gitlab.api("GET", f"/projects/{pid}/deploy_keys"):
            gitlab.api("PUT", f"/projects/{pid}/deploy_keys/{key['id']}", {"can_push": False})
        before = gitlab.branch(pid, "homolog")["commit"]["id"]
        _send(page, "anote com chave só de leitura")
        page.locator('[data-testid=tab-repository]').click()
        _wait_badge(page, "envio pendente")
        assert gitlab.branch(pid, "homolog")["commit"]["id"] == before
    finally:
        gitlab.delete_project(pid)
