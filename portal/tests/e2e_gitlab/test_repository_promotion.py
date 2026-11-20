"""E2E com GitLab local: promoção por merge request, pipeline e tag; promoção sem token; chave só
leitura (change add-system-git-remote, tarefa 9.1)."""

import subprocess
import time
import uuid

import pytest

import gitlab
from conftest import PORTAL_CONTAINER
from test_repository_link import _send, _wait_badge
from test_repository_sync import _linked_system

pytestmark = pytest.mark.e2e


def _expect_notification(page, expected: str, timeout_ms: int = 30_000) -> None:
    """Espera uma notificação com `expected`; se outra aparecer, falha mostrando o texto dela."""
    deadline = time.time() + timeout_ms / 1000
    seen: list[str] = []
    while time.time() < deadline:
        texts = page.locator(".q-notification").all_inner_texts()
        seen.extend(t for t in texts if t not in seen)
        if any(expected in t for t in texts):
            return
        page.wait_for_timeout(300)
    raise AssertionError(f"notificação {expected!r} não apareceu; apareceram: {seen}")


def test_promocao_merge_e_tag_da_versao(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    pid = project["id"]
    try:
        _send(page, "anote mudança para promover")
        # o envio do checkpoint termina logo depois da execução: espera ele chegar ao GitLab
        # (promover antes disso é recusado, corretamente, por haver checkpoint não enviado)
        local = subprocess.run(["docker", "exec", PORTAL_CONTAINER, "git", "--git-dir", f"/gitdirs/{slug}",
                                "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
        gitlab.wait_branch(pid, "homolog", sha=local)
        page.locator('[data-testid=tab-repository]').click()
        _wait_badge(page, "sincronizado")

        # token de projeto (Developer, api), testado pela aba
        page.locator('[data-testid=repo-token]').fill(gitlab.project_token(pid))
        page.locator('[data-testid=repo-token-save]').click()
        _expect_notification(page, "Token cadastrado")
        page.locator('[data-testid=repo-token-test]').click()
        _expect_notification(page, "Token válido")

        # solicitar promoção abre o MR; de novo, mostra o mesmo
        page.locator('[data-testid=repo-promote]').click()
        _expect_notification(page, "Merge request aberto")
        mrs = gitlab.open_mrs(pid)
        assert len(mrs) == 1
        url = page.locator('[data-testid=repo-mr-url]').inner_text().strip()
        assert url == mrs[0]["web_url"]
        page.locator('[data-testid=repo-promote]').click()
        _expect_notification(page, "Já existe um merge request aberto")
        assert len(gitlab.open_mrs(pid)) == 1, "nenhum MR duplicado"

        # pipeline de validação verde, merge pelo humano e tag criada pelo pipeline da main
        merged = gitlab.merge_when_green(pid, mrs[0]["iid"])
        assert merged["state"] == "merged"
        main_tip = gitlab.branch(pid, "main")["commit"]["id"]
        tag = gitlab.wait_tag(pid, main_tip)
        assert tag["name"].startswith("v1.0.")

        # sem token, a promoção só mostra o link de criação
        page.locator('[data-testid=repo-token-remove]').click()
        _expect_notification(page, "Token removido")
        page.locator('[data-testid=repo-promote]').click()
        _expect_notification(page, "Sem token de API")
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
