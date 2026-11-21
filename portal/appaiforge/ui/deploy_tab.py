"""Aba Implantação de um sistema só implantação (change add-deploy-only-system, D9): repositório
com chave só leitura, versões com "Implantar", versão atual, modo automático, webhook e histórico.
Rollback é implantar uma tag anterior pelo mesmo botão."""

from __future__ import annotations

from nicegui import run as _run
from nicegui import ui

from .. import deploy, git_sync
from ..config import get_settings
from ..services import git_remote
from .common import notify

_STATUS = {"running": "em andamento", "succeeded": "sucesso", "failed": "falha", "rolled_back": "voltou à anterior"}
_TRIGGER = {"manual": "manual", "polling": "consulta periódica", "webhook": "webhook"}


def _webhook_url(system_id: str) -> str:
    settings = get_settings()
    base = (settings.webhook_base_url or settings.public_base_url or "").rstrip("/")
    return f"{base}/hooks/gitlab/{system_id}"


def render_deploy_tab(system, user) -> None:
    ui.label(
        "Implanta neste sistema só versões (tags) do repositório GitLab que estão na branch de "
        "destino. O portal só lê o repositório; nunca envia nada a ele."
    ).classes("text-sm text-gray-500 mb-2")

    view = git_remote.ensure_remote(system, user)
    settings = deploy.get_deploy_settings(system.id)
    state: dict = {"pending_host": None}

    # --- chave só leitura -------------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl"):
        ui.label("Chave de implantação (só leitura)").classes("font-semibold")
        ui.label(
            "Cadastre esta chave pública no projeto do GitLab (Configurações > Repositório > Chaves de "
            "implantação) SEM permissão de escrita: este portal só lê o repositório."
        ).classes("text-sm text-gray-500")
        key_area = ui.textarea(value=view["public_key"]).props(
            "readonly outlined autogrow data-testid=deploy-public-key").classes("w-full font-mono text-xs")
        ui.label(f"Impressão digital: {view['fingerprint']}").classes("text-xs text-gray-500 font-mono")
        ui.button("Copiar chave", icon="content_copy",
                  on_click=lambda: (ui.clipboard.write(key_area.value), notify("Chave pública copiada.", "info"))
                  ).props("outline data-testid=deploy-copy-key")

    # --- repositório, branch de destino e padrão de tags ------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Repositório").classes("font-semibold")
        url_input = ui.input("Endereço SSH do repositório", value=view["url"],
                             placeholder="git@gitlab.exemplo.com:time/app.git").classes("w-full").props("data-testid=deploy-url")
        with ui.row().classes("w-full gap-2"):
            target_input = ui.input("Branch de destino", value=view["target_branch"]).classes("w-56").props(
                "data-testid=deploy-target-branch")
            pattern_input = ui.input("Padrão de tags", value=settings.tag_pattern).classes("w-56").props(
                "data-testid=deploy-tag-pattern")

        def save_repo() -> None:
            target = (target_input.value or "main").strip()
            try:
                git_remote.configure(system, user, url=url_input.value, target_branch=target,
                                     working_branch="homolog" if target != "homolog" else "main")
                current = deploy.get_deploy_settings(system.id)
                deploy.update_settings(system, user, tag_pattern=pattern_input.value, mode=current.mode,
                                       detection=current.detection)
            except (git_remote.InvalidRemote, git_remote.NotPermitted, deploy.DeployError) as exc:
                notify(str(exc), "negative")
                return
            notify("Repositório salvo. Teste a conexão para confirmar o servidor.", "positive")
            refresh_versions()

        with ui.row().classes("gap-2 items-center"):
            ui.button("Salvar", icon="save", on_click=save_repo).props("data-testid=deploy-save")
            ui.button("Testar conexão", icon="lan", on_click=lambda: test_connection()).props(
                "outline data-testid=deploy-test-connection")
            host_state = ui.label("").classes("text-sm").props("data-testid=deploy-host-state")

    def _host_state() -> None:
        current = git_remote.get_view(system)
        confirmed = bool(current and current["host_key_confirmed"])
        host_state.set_text("Servidor confirmado." if confirmed else "Servidor ainda não confirmado.")

    _host_state()

    with ui.dialog() as host_dialog, ui.card().classes("w-[32rem]"):
        ui.label("Confirmar o servidor").classes("font-semibold text-lg")
        ui.label("Confira se a impressão digital abaixo é a do seu GitLab antes de continuar.").classes("text-sm")
        host_fp = ui.label("").classes("font-mono text-xs").props("data-testid=deploy-host-fingerprint")

        async def confirm_host() -> None:
            git_remote.confirm_host_key(system, user, state["pending_host"])
            host_dialog.close()
            await _check_access()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=host_dialog.close).props("flat")
            ui.button("Confirmar", on_click=confirm_host).props("data-testid=deploy-confirm-host")

    async def _check_access() -> None:
        secrets = git_remote.load_secrets(system.id)
        try:
            await _run.io_bound(git_sync.check_access, system.slug, secrets)
        except git_sync.RemoteError as exc:
            notify(str(exc), "negative")
            return
        notify("Conexão válida.", "positive")
        _host_state()
        refresh_versions()

    async def test_connection() -> None:
        current = git_remote.get_view(system)
        if not current or not current["url"]:
            notify("Salve o endereço do repositório antes de testar.", "warning")
            return
        try:
            scanned = await _run.io_bound(git_sync.scan_host_key, git_remote.parse_remote_url(current["url"]))
        except git_sync.RemoteError as exc:
            notify(str(exc), "negative")
            return
        secrets = git_remote.load_secrets(system.id)
        if secrets.host_key and set(secrets.host_key.splitlines()) & set(scanned.key.splitlines()):
            await _check_access()
            return
        state["pending_host"] = scanned.key
        host_fp.set_text("\n".join(scanned.fingerprints))
        host_dialog.open()

    # --- versão atual e versões -------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Versões").classes("font-semibold")
            ui.button("Atualizar", icon="refresh", on_click=lambda: refresh_versions()).props(
                "flat dense data-testid=deploy-refresh")
        current_label = ui.label("").classes("text-sm").props("data-testid=deploy-current")
        versions_box = ui.column().classes("w-full gap-1")

    async def do_deploy(tag: str) -> None:
        notify(f"Implantando {tag}…", "info")
        try:
            result = await _run.io_bound(deploy.deploy_by_user, system, user, tag)
        except deploy.DeployError as exc:
            notify(str(exc), "negative")
            return
        if result["status"] == "succeeded":
            notify(f"{tag} implantada." + (f" {result['detail']}" if result["detail"] else ""), "positive")
        else:
            notify(f"{tag} não foi implantada: {result['detail']}", "negative")
        refresh_versions()
        refresh_history()

    def refresh_versions() -> None:
        current = deploy.current_deployment(system.id)
        current_label.set_text(
            f"Versão atual: {current['tag']} ({current['commit_sha'][:8]})" if current else "Nenhuma versão implantada ainda."
        )
        versions_box.clear()
        with versions_box:
            try:
                versions = deploy.list_versions(system)
            except (deploy.DeployError, git_sync.RemoteError, git_remote.InvalidRemote) as exc:
                ui.label(str(exc)).classes("text-sm text-gray-500").props("data-testid=deploy-versions-error")
                return
            if not versions:
                ui.label("Nenhuma tag do padrão no repositório.").classes("text-sm text-gray-500")
                return
            for version in versions:
                with ui.row().classes("w-full items-center gap-3").props(f"data-testid=deploy-version-{version['tag']}"):
                    ui.label(version["tag"]).classes("font-mono w-32")
                    ui.label(version["sha"][:8]).classes("font-mono text-xs text-gray-500 w-20")
                    if version["current"]:
                        ui.badge("atual", color="positive").props("data-testid=deploy-version-current")
                    elif version["deployed"]:
                        ui.badge("já implantada", color="grey")
                    ui.space()
                    ui.button("Implantar", icon="rocket_launch",
                              on_click=lambda t=version["tag"]: do_deploy(t)).props(
                        f"dense outline data-testid=deploy-run-{version['tag']}")

    # --- modo automático e webhook ----------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Implantação automática").classes("font-semibold")
        ui.label(
            "Ligada, implanta a tag mais nova do padrão desde que ela nunca tenha sido implantada neste "
            "sistema — voltar manualmente a uma versão anterior permanece até sair uma tag nova."
        ).classes("text-sm text-gray-500")
        with ui.row().classes("items-center gap-4"):
            auto_switch = ui.switch("Automática", value=settings.mode == "automatic").props("data-testid=deploy-auto")
            detection_select = ui.select({"polling": "Consulta periódica", "webhook": "Webhook do GitLab"},
                                         value=settings.detection, label="Detecção").classes("w-56").props(
                "data-testid=deploy-detection")

        def save_auto() -> None:
            current = deploy.get_deploy_settings(system.id)
            try:
                deploy.update_settings(system, user, tag_pattern=current.tag_pattern,
                                       mode="automatic" if auto_switch.value else "manual",
                                       detection=detection_select.value)
            except deploy.DeployError as exc:
                notify(str(exc), "negative")
                return
            notify("Implantação automática salva.", "positive")

        ui.button("Salvar", icon="save", on_click=save_auto).props("data-testid=deploy-auto-save")

        ui.separator().classes("my-2")
        ui.label("Webhook do GitLab").classes("font-medium")
        ui.label(
            "Cadastre no projeto do GitLab (Configurações > Webhooks), com o evento de tag, o endereço e o "
            "segredo abaixo. O GitLab precisa alcançar este portal; senão, use a consulta periódica."
        ).classes("text-sm text-gray-500")
        ui.input("Endereço", value=_webhook_url(system.id)).props("readonly data-testid=deploy-webhook-url").classes("w-full font-mono text-xs")
        secret_input = ui.input("Segredo", value=deploy.webhook_secret(system.id)).props(
            "readonly data-testid=deploy-webhook-secret").classes("w-full font-mono text-xs")

        def rotate_secret() -> None:
            secret_input.set_value(deploy.rotate_webhook_secret(system, user))
            notify("Segredo trocado. Atualize o webhook no GitLab.", "info")

        with ui.row().classes("gap-2"):
            ui.button("Copiar segredo", icon="content_copy",
                      on_click=lambda: (ui.clipboard.write(secret_input.value), notify("Segredo copiado.", "info"))
                      ).props("outline")
            ui.button("Trocar segredo", icon="autorenew", on_click=rotate_secret).props(
                "outline data-testid=deploy-webhook-rotate")

    # --- histórico ---------------------------------------------------------------------------
    with ui.card().classes("w-full max-w-3xl mt-2"):
        ui.label("Histórico de implantações").classes("font-semibold")
        history_box = ui.column().classes("w-full gap-1").props("data-testid=deploy-history")

    def refresh_history() -> None:
        history_box.clear()
        with history_box:
            rows = deploy.list_deployments(system.id)
            if not rows:
                ui.label("Nenhuma implantação ainda.").classes("text-sm text-gray-500")
                return
            for row in rows:
                with ui.column().classes("w-full gap-0 border-b pb-1").props(f"data-testid=deploy-history-{row['id']}"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label(row["tag"]).classes("font-mono")
                        ui.label((row["commit_sha"] or "")[:8]).classes("font-mono text-xs text-gray-500")
                        ui.badge(_STATUS.get(row["status"], row["status"]),
                                 color={"succeeded": "positive", "running": "info"}.get(row["status"], "negative")
                                 ).props(f"data-testid=deploy-history-status-{row['status']}")
                        ui.label(_TRIGGER.get(row["trigger"], row["trigger"])).classes("text-xs text-gray-500")
                        ui.label((row["created_at"] or "")[:19].replace("T", " ")).classes("text-xs text-gray-500")
                    if row["detail"]:
                        ui.label(row["detail"]).classes("text-xs text-gray-500")

    refresh_versions()
    refresh_history()
    ui.timer(10.0, refresh_history)
