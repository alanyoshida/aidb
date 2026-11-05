"""Leitura somente-leitura dos arquivos gerados no workspace (capability workspace-viewer).

Isolado da UI (NiceGUI) para ser testável sem subir página nem Docker — mesmo
espírito de `checkpoints.py` (serviço) vs. os `_render_*` de `system_detail.py`.
"""

import os

from .checkpoints import workspace_dir
from .models import System

IGNORED_DIRS = {".venv", "__pycache__", ".git", ".nicegui", "node_modules"}

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
        if entry.name in IGNORED_DIRS:
            continue
        rel_path = os.path.join(rel, entry.name) if rel else entry.name
        if entry.is_dir():
            children = _build_nodes(root, rel_path)
            if not children:
                continue
            nodes.append({"id": rel_path, "label": entry.name, "children": children})
        else:
            nodes.append({"id": rel_path, "label": entry.name})
    return nodes


def list_tree(system: System) -> list[dict]:
    """Árvore de arquivos do projeto gerado, no formato de nodes do ui.tree.

    Devolve lista vazia quando `app/` ainda não existe (projeto não gerado)."""
    return _build_nodes(project_dir(system))


def language_for(rel_path: str) -> str | None:
    """Linguagem do ui.codemirror inferida pela extensão; None se desconhecida."""
    _, ext = os.path.splitext(rel_path)
    return EXT_LANGUAGE.get(ext.lower())


def read_file(system: System, rel_path: str) -> FileContent:
    """Lê `rel_path` dentro de `project_dir(system)`.

    Recusa escapar da pasta do projeto, corta em `MAX_FILE_SIZE` e devolve um
    `FileContent` com `binary=True` (em vez de lançar exceção) quando o
    conteúdo não decodifica como UTF-8."""
    base = os.path.realpath(project_dir(system))
    target = os.path.realpath(os.path.join(base, rel_path))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"caminho fora do projeto: {rel_path!r}")

    with open(target, "rb") as f:
        raw = f.read(MAX_FILE_SIZE)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return FileContent(text=None, language=None, binary=True)

    return FileContent(text=text, language=language_for(rel_path), binary=False)
