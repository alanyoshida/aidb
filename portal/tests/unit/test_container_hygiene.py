"""Nenhum segredo nas imagens do projeto, nas duas camadas que valem antes do build (change
add-ci-workflow, design D10): Dockerfiles sem ARG/ENV com nome de segredo (o valor ficaria no
histórico da imagem) e contextos de build que excluem arquivos de segredo. A terceira camada,
a checagem da imagem construída antes do push, roda na CI."""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
# imagens do projeto, com o contexto de build de cada uma
DOCKERFILES = {
    ROOT / "deploy" / "portal.Dockerfile": ROOT,
    ROOT / "base-image" / "Dockerfile": ROOT / "base-image",
    ROOT / "base-image" / "Dockerfile.claude-code": ROOT / "base-image",
}
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY", re.IGNORECASE)
SECRET_PATTERNS = ["**/.env", "**/.env.*", "**/*.env", "!**/*.env.example", "**/*.pem", "**/*.key",
                   "**/*.p12", "**/id_rsa*", "**/id_ed25519*", "**/.npmrc", "**/.pypirc", "**/.netrc"]


def _declared_names(dockerfile: pathlib.Path) -> list[tuple[int, str, str]]:
    """(linha, instrução, nome) de cada ARG e ENV, com continuações de linha juntadas."""
    names, logical, start = [], "", 0
    for n, raw in enumerate(dockerfile.read_text().splitlines(), 1):
        if not logical:
            start = n
        logical += raw.rstrip("\\").strip() + " "
        if raw.rstrip().endswith("\\"):
            continue
        m = re.match(r"(?i)(ARG|ENV)\s+(.*)", logical.strip())
        if m:
            instr, rest = m.group(1).upper(), m.group(2)
            for token in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)(?:=|\s|$)", rest) if "=" in rest else rest.split()[:1]:
                names.append((start, instr, token))
        logical = ""
    return names


def test_dockerfiles_do_projeto_existem():
    """Guarda: se um Dockerfile mudar de lugar, os testes abaixo passariam sem olhar nada."""
    assert all(p.is_file() for p in DOCKERFILES)


@pytest.mark.parametrize("dockerfile", list(DOCKERFILES), ids=lambda p: str(p.relative_to(ROOT)))
def test_dockerfile_sem_arg_nem_env_de_segredo(dockerfile):
    found = [f"{dockerfile.name}:{n}: {instr} {name}" for n, instr, name in _declared_names(dockerfile)
             if SECRET_NAME.search(name)]
    assert not found, "segredo declarado no Dockerfile (fica no histórico da imagem):\n" + "\n".join(found)


@pytest.mark.parametrize("context", sorted(set(DOCKERFILES.values())), ids=lambda p: str(p.relative_to(ROOT)) or ".")
def test_contexto_de_build_exclui_arquivos_de_segredo(context):
    ignore = context / ".dockerignore"
    assert ignore.is_file(), f"{ignore.relative_to(ROOT)} ausente"
    lines = {line.strip() for line in ignore.read_text().splitlines()}
    missing = [p for p in SECRET_PATTERNS if p not in lines]
    assert not missing, f"{ignore.relative_to(ROOT)} sem os padrões: {missing}"


def test_detector_pega_arg_de_segredo(tmp_path):
    """O próprio detector: ARG e ENV com nome de segredo, inclusive em ENV com várias variáveis."""
    f = tmp_path / "Dockerfile"
    f.write_text("FROM x\nARG GITLAB_TOKEN\nENV A=1 \\\n    DB_PASSWORD=x\nENV HOME=/h\n")
    assert [(i, n) for _, i, n in _declared_names(f) if SECRET_NAME.search(n)] == [
        ("ARG", "GITLAB_TOKEN"), ("ENV", "DB_PASSWORD")]
