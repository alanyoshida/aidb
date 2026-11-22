"""Uma versão só para portal, chart e imagens padrão dos sistemas (change version-alignment, D5).

A fonte é o `version` do `pyproject.toml`. Este teste aponta toda cópia que ficou para trás numa
release: o pacote instalado, o `uv.lock`, o `Chart.yaml`, os valores do chart e as referências às
imagens da plataforma nos docs. Tags que não são semver (`pilot`, `latest`) e imagens com um
registro na frente (`registro.exemplo/appaiforge/base:1.4.2`) ficam de fora."""

import pathlib
import re
import tomllib

import yaml

from appaiforge import __version__

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy" / "helm" / "appaiforge-portal"
IMAGE_REF = re.compile(r"(?<![\w./-])appaiforge/(?:portal|base|claude-code):(\d+\.\d+\.\d+)\b")


def _version() -> str:
    return tomllib.loads((ROOT / "portal" / "pyproject.toml").read_text())["project"]["version"]


def _docs() -> list[pathlib.Path]:
    files = [ROOT / "README.md", CHART / "values.yaml", CHART / "values-production.yaml"]
    files += [p for p in (ROOT / "docs").glob("*.md") if not p.name.startswith("roadmap-")]
    files += [p for p in (ROOT / "deploy").rglob("*.md")]
    return sorted(set(files))


def test_pacote_instalado_e_lock_com_a_versao_do_pyproject():
    lock = tomllib.loads((ROOT / "portal" / "uv.lock").read_text())
    locked = next(p["version"] for p in lock["package"] if p["name"] == "appaiforge-portal")
    assert (__version__, locked) == (_version(), _version())


def test_chart_com_a_versao_do_portal():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    tags = {name: yaml.safe_load((CHART / name).read_text())["image"]["tag"]
            for name in ("values.yaml", "values-production.yaml")}
    expected = _version()
    assert (chart["version"], chart["appVersion"]) == (expected, expected)
    assert tags == {"values.yaml": expected, "values-production.yaml": expected}


def test_docs_citam_as_imagens_da_plataforma_na_versao_do_portal():
    expected = _version()
    stale = [f"{path.relative_to(ROOT)}:{n}: {m.group(0)}"
             for path in _docs()
             for n, line in enumerate(path.read_text().splitlines(), 1)
             for m in IMAGE_REF.finditer(line) if m.group(1) != expected]
    assert not stale, "referências com outra versão:\n" + "\n".join(stale)


def test_docs_tem_referencias_para_conferir():
    """Guarda do teste acima: se a busca deixar de achar referências, ele passaria vazio."""
    assert sum(len(IMAGE_REF.findall(p.read_text())) for p in _docs()) >= 10
