"""E2E com GitLab local: sincronização com merges humanos, alterações não salvas e divergência
(change add-system-git-remote, tarefas 5.4, 6.2 e 7.4)."""

import subprocess
import time
import uuid

import pytest

import gitlab
from conftest import PORTAL_CONTAINER
from test_repository_link import _badge_text, _create_user, _login, _send, _wait_active, _wait_badge

pytestmark = pytest.mark.e2e


def _agent_write(slug: str, path: str, content: str) -> None:
    """Escreve no workspace fora de uma execução, no lugar do agente. Como root: no stack E2E o
    harness fake roda dentro do portal e cria os arquivos como root, então o uid do agente não
    conseguiria sobrescrevê-los (no ambiente real o agente é dono do que escreve)."""
    subprocess.run(["docker", "exec", PORTAL_CONTAINER, "sh", "-c",
                    f'mkdir -p "$(dirname /workspaces/{slug}/{path})" && printf "%s" "$1" > /workspaces/{slug}/{path}',
                    "sh", content], check=True)


def _agent_read(slug: str, path: str) -> str | None:
    r = subprocess.run(["docker", "exec", PORTAL_CONTAINER, "cat", f"/workspaces/{slug}/{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _linked_system(page, suffix: str):
    """Editor, sistema e projeto vazio no GitLab, vinculados pela aba e com um primeiro envio."""
    editor = f"sync-editor-{suffix}@e2e.local"
    slug = f"sync-{suffix}"
    _create_user(page, editor, "editor")
    project = gitlab.create_system_project(f"sincronia-{suffix}")
    _login(page, editor, "pw-e2e")
    page.get_by_role("button", name="Novo sistema").click()
    page.locator('[data-testid=system-name]').fill("Sistema Sincronia")
    page.locator('[data-testid=system-slug]').fill(slug)
    page.locator('[data-testid=create-system]').click()
    _wait_active(page)
    page.locator('[data-testid=tab-repository]').click()
    gitlab.add_deploy_key(project["id"], page.locator('[data-testid=repo-public-key]').input_value())
    page.locator('[data-testid=repo-url]').fill(gitlab.ssh_url(project))
    page.locator('[data-testid=repo-api-url]').fill(gitlab.INTERNAL_API)
    page.locator('[data-testid=repo-save]').click()
    page.locator('[data-testid=repo-test]').click()
    page.locator('[data-testid=repo-confirm-host]').click()
    page.get_by_text("Conexão válida").wait_for(timeout=30_000)
    page.locator('[data-testid=repo-enable]').click()
    page.get_by_text("Vínculo ativado").wait_for(timeout=60_000)
    _send(page, "anote base")
    gitlab.wait_branch(project["id"], "homolog")
    gitlab.bootstrap_main(project["id"])
    return slug, project


def test_merge_humano_chega_antes_da_execucao_seguinte(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    try:
        merged = gitlab.human_merge_request(project["id"], "homolog", "humano.txt", "do merge request\n",
                                            "adiciona humano.txt")
        assert merged["state"] == "merged"
        _send(page, "anote depois do merge")
        assert _agent_read(slug, "humano.txt") == "do merge request\n"
        tip = gitlab.wait_branch(project["id"], "homolog")["commit"]["id"]
        local = subprocess.run(["docker", "exec", PORTAL_CONTAINER, "git", "--git-dir", f"/gitdirs/{slug}",
                                "rev-parse", "main"], capture_output=True, text=True).stdout.strip()
        deadline = time.time() + 60
        while tip != local and time.time() < deadline:
            time.sleep(2)
            tip = gitlab.branch(project["id"], "homolog")["commit"]["id"]
        assert tip == local, "o envio depois do merge humano foi aceito"
        page.get_by_role("tab", name="Checkpoints").click()
        page.locator('[data-testid="checkpoint-entry:remote"]').first.wait_for(timeout=30_000)
    finally:
        gitlab.delete_project(project["id"])


def test_alteracoes_nao_salvas_bloqueiam_e_o_editor_decide(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    try:
        # salvar
        gitlab.commit_file(project["id"], "homolog", "remoto-1.txt", "um\n", "mudança no remoto")
        _agent_write(slug, "rascunho.txt", "guardar\n")
        page.get_by_role("tab", name="Chat").click()
        page.locator('[data-testid=chat-input]').fill("crie o painel")
        page.locator('[data-testid=chat-send]').click()
        page.get_by_text("salve ou descarte").first.wait_for(timeout=60_000)
        page.locator('[data-testid=tab-repository]').click()
        page.locator('[data-testid=repo-unsaved]').wait_for(state="visible", timeout=15_000)
        page.locator('[data-testid=repo-save-unsaved]').click()
        page.get_by_text("Alterações salvas").wait_for(timeout=60_000)
        assert _agent_read(slug, "rascunho.txt") == "guardar\n" and _agent_read(slug, "remoto-1.txt") == "um\n"

        # descartar
        gitlab.commit_file(project["id"], "homolog", "remoto-2.txt", "dois\n", "outra mudança no remoto")
        _agent_write(slug, "lixo.txt", "jogar fora\n")
        page.locator('[data-testid=repo-sync-now]').click()
        page.get_by_text("salve ou descarte").first.wait_for(timeout=60_000)
        page.locator('[data-testid=repo-unsaved]').wait_for(state="visible", timeout=15_000)
        page.locator('[data-testid=repo-discard-unsaved]').click()
        page.locator('[data-testid=repo-discard-confirm]').click()
        page.get_by_text("Alterações descartadas").wait_for(timeout=60_000)
        assert _agent_read(slug, "lixo.txt") is None and _agent_read(slug, "remoto-2.txt") == "dois\n"
        page.locator('[data-testid=repo-unsaved]').wait_for(state="hidden", timeout=15_000)
    finally:
        gitlab.delete_project(project["id"])


def test_divergencia_aparece_e_adotar_o_remoto_resolve(page):
    suffix = uuid.uuid4().hex[:8]
    slug, project = _linked_system(page, suffix)
    try:
        gitlab.commit_file(project["id"], "homolog", "notas.txt", "do humano\n", "humano altera as notas")
        _agent_write(slug, "notas.txt", "do agente\n")
        page.get_by_role("tab", name="Checkpoints").click()
        page.get_by_role("button", name="Criar checkpoint agora").click()
        page.locator('[data-testid=tab-repository]').click()
        _wait_badge(page, "divergente")
        page.locator('[data-testid=repo-diverged]').wait_for(state="visible", timeout=15_000)
        assert "notas.txt" in page.locator('[data-testid=repo-conflict-files]').inner_text()
        assert _agent_read(slug, "notas.txt") == "do agente\n", "sem marcas de conflito"

        page.locator('[data-testid=repo-adopt]').click()
        page.locator('[data-testid=repo-adopt-list]').get_by_text("checkpoint manual").wait_for(timeout=15_000)
        page.locator('[data-testid=repo-adopt-confirm]').click()
        page.get_by_text("Versão do remoto adotada").wait_for(timeout=60_000)
        _wait_badge(page, "sincronizado")
        assert _agent_read(slug, "notas.txt") == "do humano\n"
    finally:
        gitlab.delete_project(project["id"])
