"""Leitura somente-leitura dos arquivos gerados no workspace (capability workspace-viewer).

Isolado da UI (NiceGUI) para ser testável sem subir página nem Docker — mesmo
espírito de `checkpoints.py` (serviço) vs. os `_render_*` de `system_detail.py`.
"""

import logging
import os

from .checkpoints import workspace_dir
from .models import System

log = logging.getLogger(__name__)

IGNORED_DIRS = {".venv", "__pycache__", ".git", ".nicegui", "node_modules"}
# marcador de pasta vazia (o `openspec init` cria um em specs/): não é conteúdo
IGNORED_FILES = {".gitkeep"}

MAX_FILE_SIZE = 1024 * 1024  # 1 MB

EXT_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".json": "JSON",
    ".toml": "TOML",
    ".lock": "TOML",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".html": "HTML",
    ".css": "CSS",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
    ".xml": "XML",
}

FOLDER_ICON = "folder"
DEFAULT_FILE_ICON = "insert_drive_file"

# Nomes de ícones do Material Icons (já embutido no NiceGUI, sem CDN externo)
# — não há logos por linguagem nesse conjunto, então agrupamos por categoria
# ampla em vez de tentar imitar os ícones coloridos por extensão do VS Code.
_ICON_BY_EXT: dict[str, str] = {
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".html": "code",
    ".css": "code",
    ".sh": "terminal",
    ".sql": "code",
    ".json": "data_object",
    ".toml": "settings",
    ".lock": "settings",
    ".yml": "settings",
    ".yaml": "settings",
    ".ini": "settings",
    ".cfg": "settings",
    ".env": "settings",
    ".md": "article",
    ".txt": "article",
    ".xml": "data_object",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
}


def icon_for(rel_path: str) -> str:
    """Ícone (Material Icons) para o arquivo, inferido pela extensão."""
    _, ext = os.path.splitext(rel_path)
    return _ICON_BY_EXT.get(ext.lower(), DEFAULT_FILE_ICON)


class FileContent:
    def __init__(self, text: str | None, language: str | None, binary: bool):
        self.text = text
        self.language = language
        self.binary = binary


def project_dir(system: System) -> str:
    """Pasta onde o agente gera o projeto do sistema (`<workspace>/app`)."""
    return os.path.join(workspace_dir(system), "app")


def _build_nodes(root: str, rel: str = "") -> list[dict]:
    """Nodes recursivos no formato do ui.tree, a partir de `root/rel`."""
    current = os.path.join(root, rel) if rel else root
    try:
        entries = sorted(os.scandir(current), key=lambda e: (not e.is_dir(), e.name))
    except FileNotFoundError:
        return []

    nodes: list[dict] = []
    for entry in entries:
        if entry.name in IGNORED_DIRS or entry.name in IGNORED_FILES:
            continue
        rel_path = os.path.join(rel, entry.name) if rel else entry.name
        if entry.is_dir():
            children = _build_nodes(root, rel_path)
            if not children:
                continue
            nodes.append({"id": rel_path, "label": entry.name, "icon": FOLDER_ICON, "children": children})
        else:
            nodes.append({"id": rel_path, "label": entry.name, "icon": icon_for(entry.name)})
    return nodes


# Planejamento do OpenSpec no workspace (`<workspace>/openspec`): só as changes e as specs, que
# é o que o editor quer validar (proposal.md, design.md, tasks.md). O resto da pasta nasce no
# `openspec init` de todo sistema e faria a aba parecer "com arquivos" antes de qualquer geração.
OPENSPEC_PREFIX = "@openspec/"
OPENSPEC_DIRS = ("changes", "specs")


def openspec_dir(system: System) -> str:
    return os.path.join(workspace_dir(system), "openspec")


def _remote() -> bool:
    """Sob o driver Kubernetes o workspace só existe no PVC do Pod: lista e lê por exec."""
    from .config import get_settings

    return get_settings().provisioning_driver == "kubernetes"


def _nodes_from_paths(paths: list[str], prefix: str = "") -> list[dict]:
    """Mesmos nodes de `_build_nodes`, a partir de uma lista de arquivos (relativos à raiz da
    árvore), para o caso remoto. Diretórios antes dos arquivos, cada grupo em ordem de nome."""
    tree: dict = {}
    for path in paths:
        parts = path.split("/")
        if any(p in IGNORED_DIRS for p in parts) or parts[-1] in IGNORED_FILES:
            continue
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if node is None:
                break
        else:
            node.setdefault(parts[-1], None)

    def build(level: dict, rel: str) -> list[dict]:
        nodes = []
        for name in sorted(k for k, v in level.items() if v is not None):
            rel_path = f"{rel}/{name}" if rel else name
            children = build(level[name], rel_path)
            if children:
                nodes.append({"id": rel_path, "label": name, "icon": FOLDER_ICON, "children": children})
        for name in sorted(k for k, v in level.items() if v is None):
            rel_path = f"{rel}/{name}" if rel else name
            nodes.append({"id": rel_path, "label": name, "icon": icon_for(name)})
        return nodes

    return build(tree, prefix)


def _remote_paths(system: System) -> list[str]:
    from .drivers import kubernetes_driver

    roots = ["app"] + [f"openspec/{name}" for name in OPENSPEC_DIRS]
    return kubernetes_driver.list_workspace_files(system, roots, IGNORED_DIRS)


def _openspec_nodes(system: System, remote_paths: list[str] | None = None) -> list[dict]:
    root = openspec_dir(system)
    children = []
    for name in OPENSPEC_DIRS:
        if remote_paths is None:
            sub = _build_nodes(root, name)
        else:
            inside = [p[len("openspec/"):] for p in remote_paths if p.startswith(f"openspec/{name}/")]
            sub = [n for top in _nodes_from_paths(inside) if top["id"] == name for n in top["children"]]
        if sub:
            children.append({"id": OPENSPEC_PREFIX + name, "label": name, "icon": FOLDER_ICON, "children": sub})
    for child in children:
        _prefix_ids(child["children"])
    if not children:
        return []
    return [{"id": OPENSPEC_PREFIX.rstrip("/"), "label": "openspec", "icon": FOLDER_ICON, "children": children}]


def _prefix_ids(nodes: list[dict]) -> None:
    for node in nodes:
        node["id"] = OPENSPEC_PREFIX + node["id"]
        _prefix_ids(node.get("children", []))


def display_path(rel_path: str) -> str:
    """Caminho para mostrar ao usuário (sem o marcador interno do OpenSpec)."""
    return rel_path[1:] if rel_path.startswith(OPENSPEC_PREFIX) else rel_path


def list_tree(system: System) -> list[dict]:
    """Árvore de arquivos do projeto gerado, no formato de nodes do ui.tree, mais uma pasta
    `openspec` com as changes e specs do sistema quando houver alguma.

    Devolve lista vazia quando nada disso existe ainda (projeto não gerado)."""
    if _remote():
        try:
            paths = _remote_paths(system)
        except Exception:  # noqa: BLE001 - Pod recriando/fora do ar: árvore vazia, sem quebrar a aba
            log.warning("não foi possível listar o workspace de %s", system.slug, exc_info=True)
            return []
        app = _nodes_from_paths([p[len("app/"):] for p in paths if p.startswith("app/")])
        return app + _openspec_nodes(system, paths)
    return _build_nodes(project_dir(system)) + _openspec_nodes(system)


def language_for(rel_path: str) -> str | None:
    """Linguagem do ui.codemirror inferida pela extensão; None se desconhecida."""
    _, ext = os.path.splitext(rel_path)
    return EXT_LANGUAGE.get(ext.lower())


def read_file(system: System, rel_path: str) -> FileContent:
    """Lê `rel_path` dentro de `project_dir(system)`, ou dentro de `openspec/changes` e
    `openspec/specs` quando o caminho vem da pasta openspec da árvore.

    Recusa escapar dessas pastas, corta em `MAX_FILE_SIZE` e devolve um
    `FileContent` com `binary=True` (em vez de lançar exceção) quando o
    conteúdo não decodifica como UTF-8."""
    if _remote():
        raw = _read_remote(system, rel_path)
    else:
        raw = _read_local(system, rel_path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return FileContent(text=None, language=None, binary=True)

    return FileContent(text=text, language=language_for(rel_path), binary=False)


def _read_remote(system: System, rel_path: str) -> bytes:
    import posixpath

    from .drivers import kubernetes_driver

    if rel_path.startswith(OPENSPEC_PREFIX):
        inner = rel_path[len(OPENSPEC_PREFIX):]
        top = inner.split("/", 1)[0]
        if top not in OPENSPEC_DIRS:
            raise ValueError(f"caminho fora do planejamento: {rel_path!r}")
        base = f"/workspace/openspec/{top}"
        target = posixpath.normpath(f"/workspace/openspec/{inner}")
    else:
        base = "/workspace/app"
        target = posixpath.normpath(f"{base}/{rel_path}")
    if not target.startswith(base + "/"):
        raise ValueError(f"caminho fora do projeto: {rel_path!r}")
    return kubernetes_driver.read_workspace_file(system, target, base, MAX_FILE_SIZE)


def _read_local(system: System, rel_path: str) -> bytes:
    if rel_path.startswith(OPENSPEC_PREFIX):
        inner = rel_path[len(OPENSPEC_PREFIX):]
        top = inner.split("/", 1)[0]
        if top not in OPENSPEC_DIRS:
            raise ValueError(f"caminho fora do planejamento: {rel_path!r}")
        base = os.path.realpath(os.path.join(openspec_dir(system), top))
        target = os.path.realpath(os.path.join(openspec_dir(system), inner))
    else:
        base = os.path.realpath(project_dir(system))
        target = os.path.realpath(os.path.join(base, rel_path))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"caminho fora do projeto: {rel_path!r}")

    with open(target, "rb") as f:
        return f.read(MAX_FILE_SIZE)
