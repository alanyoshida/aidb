"""Isolamento do repositório git do sistema em relação ao workspace (change
`isolate-workspace-repository`, capability `workspace-repository`, requirement "Nada controlado
pelo workspace executa nas operações git").

O agente escreve livremente em `/workspace`. Este teste planta ali, exatamente como o agente
poderia, tudo o que o git interpreta como comando — hooks, `core.fsmonitor`, filtro declarado em
`.gitattributes` com definição em `.git/config`, e um `include.path` apontando para um arquivo do
workspace — e depois pede um checkpoint ao portal. Cada item plantado, se executar, cria um
arquivo marcador; nenhum marcador pode existir depois do checkpoint.

Escrito antes da correção (task 1.1) e rodado contra o código anterior para confirmar o risco: o
resultado dessa rodada está registrado no ADR da change.
"""

import os
import subprocess

import pytest

pytestmark = [pytest.mark.integration]

DRIVERS = ["docker"]
try:
    from kubernetes import config as k8s_config

    k8s_config.load_kube_config(context="kind-appaiforge-dev")
    DRIVERS.append("kubernetes")
except Exception:
    pass

K8S_CONTEXT = "kind-appaiforge-dev"
K8S_NAMESPACE = "appaiforge-test"
K8S_MARKERS = "/tmp/aidb-planted"

# Nome de cada marcador -> o que o criaria se executasse.
PLANTED = {
    "hook-pre-commit": "hook pre-commit em .git/hooks",
    "hook-post-commit": "hook post-commit em .git/hooks",
    "fsmonitor": "core.fsmonitor em .git/config",
    "filter": "filtro declarado em .gitattributes e definido em .git/config",
    "include": "filtro definido num arquivo do workspace incluído por include.path",
}


def _plant_script(ws: str, mk: str) -> str:
    """Script POSIX que planta, a partir do workspace `ws`, tudo que o git executaria. Cada
    item executado cria `mk/<nome>`; o hook pre-commit também registra o uid e se consegue
    escrever fora dos caminhos graváveis do agente (sinal de que roda fora do Landlock)."""
    return f"""
set -e
mkdir -p "{mk}"
cd "{ws}"
mkdir -p .git/hooks
cat > .git/hooks/pre-commit <<'EOF'
#!/bin/sh
touch "{mk}/hook-pre-commit"
id -u > "{mk}/hook-uid"
if touch /home/agent/.aidb-fora-do-landlock 2>/dev/null; then echo escreveu > "{mk}/hook-home"; else echo bloqueado > "{mk}/hook-home"; fi
exit 0
EOF
cat > .git/hooks/post-commit <<'EOF'
#!/bin/sh
touch "{mk}/hook-post-commit"
EOF
chmod +x .git/hooks/pre-commit .git/hooks/post-commit
cat > fsmon.sh <<'EOF'
#!/bin/sh
touch "{mk}/fsmonitor"
exit 1
EOF
chmod +x fsmon.sh
git config -f .git/config core.fsmonitor "{ws}/fsmon.sh"
git config -f .git/config filter.evil.clean "sh -c 'touch {mk}/filter; cat'"
cat > inc.cfg <<'EOF'
[filter "inc"]
	clean = sh -c 'touch {mk}/include; cat'
EOF
git config -f .git/config include.path "{ws}/inc.cfg"
printf 'evil.txt filter=evil\\ninc.txt filter=inc\\n' > .gitattributes
echo conteudo-evil > evil.txt
echo conteudo-inc > inc.txt
"""


class _Workspace:
    """Acesso ao workspace e aos marcadores como o agente os vê, por driver. Só esta classe
    conhece a diferença entre drivers; o teste em si é agnóstico."""

    def __init__(self, driver: str, system, tmp_path):
        self.driver = driver
        self.system = system
        if driver == "kubernetes":
            self.ws = "/workspace"
            self.mk = K8S_MARKERS
        else:
            from appaiforge.config import get_settings

            self.ws = os.path.join(get_settings().workspaces_dir, system.slug)
            self.mk = str(tmp_path / "markers")

    def _kubectl_exec(self, container: str, script: str) -> subprocess.CompletedProcess:
        from appaiforge.edge import system_container_name

        return subprocess.run(
            [
                "kubectl", "--context", K8S_CONTEXT, "-n", K8S_NAMESPACE, "exec",
                system_container_name(self.system.slug), "-c", container, "--", "sh", "-c", script,
            ],
            capture_output=True, text=True, timeout=60,
        )

    def run_as_agent(self, script: str) -> None:
        if self.driver == "kubernetes":
            result = self._kubectl_exec("agent", script)
        else:
            os.makedirs(self.ws, exist_ok=True)
            result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def markers(self) -> dict[str, str]:
        """Marcadores encontrados -> conteúdo. No driver Kubernetes procura em todo container do
        pod que tenha shell, porque o git do portal pode rodar em qualquer um deles."""
        found: dict[str, str] = {}
        if self.driver == "kubernetes":
            dump = f'for f in "{self.mk}"/*; do [ -e "$f" ] && echo "$(basename "$f")=$(cat "$f")"; done; true'
            for container in ("agent", "git"):
                result = self._kubectl_exec(container, dump)
                if result.returncode != 0:
                    continue  # container inexistente neste pod
                for line in result.stdout.splitlines():
                    name, _, value = line.partition("=")
                    found[f"{container}:{name}"] = value.strip()
            return found
        if os.path.isdir(self.mk):
            for name in os.listdir(self.mk):
                with open(os.path.join(self.mk, name)) as f:
                    found[name] = f.read().strip()
        return found


def _setup_env(driver: str, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPAIFORGE_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_HOST_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("APPAIFORGE_GITDIRS_DIR", str(tmp_path / "gitdirs"))
    monkeypatch.setenv("APPAIFORGE_DYNAMIC_CONFIG_DIR", str(tmp_path / "dynamic"))
    monkeypatch.setenv("APPAIFORGE_CONFIGS_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_HOST_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("APPAIFORGE_PROVISIONING_DRIVER", driver)
    if driver == "kubernetes":
        monkeypatch.setenv("APPAIFORGE_K8S_NAMESPACE", K8S_NAMESPACE)
    from appaiforge.config import get_settings

    get_settings.cache_clear()


def _new_system(driver: str):
    from appaiforge import auth
    from appaiforge.models import UserType
    from appaiforge.services import catalog
    from appaiforge.services.systems import create_system

    catalog.ensure_presets()
    editor = auth.create_user(f"isol-{driver}-{os.urandom(2).hex()}@t.local", "pw", UserType.editor.value)
    return create_system(editor, "Isolamento", f"isol-{driver}-{os.urandom(3).hex()}")


def _teardown(driver: str, system) -> None:
    if driver == "kubernetes":
        from appaiforge.provisioning import delete_system

        delete_system(system)


@pytest.fixture()
def workspace(request, tmp_path, monkeypatch, clean_db):
    driver = request.param
    _setup_env(driver, tmp_path, monkeypatch)
    system = _new_system(driver)
    if driver == "kubernetes":
        from appaiforge.drivers.kubernetes_driver import _wait_for_agent_container_started
        from appaiforge.edge import system_container_name
        from appaiforge.provisioning import provision_system

        provision_system(system)
        _wait_for_agent_container_started(system_container_name(system.slug), K8S_NAMESPACE, timeout=120)
    try:
        yield _Workspace(driver, system, tmp_path)
    finally:
        _teardown(driver, system)


@pytest.mark.parametrize("workspace", DRIVERS, indirect=True)
def test_nada_plantado_no_workspace_executa_no_checkpoint(workspace):
    from appaiforge.checkpoints import record_checkpoint

    # Primeiro checkpoint: estado inicial do repositório, antes de qualquer item plantado.
    workspace.run_as_agent(f'cd "{workspace.ws}" && echo inicial > app.txt')
    assert record_checkpoint(workspace.system, None, "inicial") is not None

    workspace.run_as_agent(_plant_script(workspace.ws, workspace.mk))
    workspace.run_as_agent(f'cd "{workspace.ws}" && echo alterado > app.txt')

    cp = record_checkpoint(workspace.system, None, "depois de plantar")
    assert cp is not None, "o checkpoint precisa ser criado mesmo com conteúdo plantado no workspace"

    found = workspace.markers()
    executed = {name: value for name, value in found.items() if name.split(":")[-1] in PLANTED}
    assert not executed, (
        "itens plantados pelo agente executaram durante o checkpoint: "
        + ", ".join(PLANTED[n.split(":")[-1]] for n in executed)
        + f" | marcadores: {found}"
    )
