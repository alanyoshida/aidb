# Design

## Context

Ver `proposal.md` — Why. O que molda a abordagem:

- `portal/appaiforge/ui/system_detail.py` já tem o padrão exato que esta change estende: `ui.tabs()` + `ui.tab_panels()`, um `_render_<aba>(system, user)` por aba, todo dentro do bloco já gated por `can_manage_system(user, system)` ([`system_detail.py:73`](../../../portal/appaiforge/ui/system_detail.py)). As abas Checkpoints, Auditoria e Uso atualizam por `ui.timer(2.0, refresh)` — poll simples, sem barramento de eventos.
- `checkpoints.workspace_dir(system)` devolve a raiz do workspace do sistema; o projeto gerado vive em `<workspace>/app` (mesma convenção do supervisor: `self.app_dir = os.path.join(workspace, "app")` em `base-image/afsupervisor/supervisor.py`).
- Protótipo validado nesta sessão (fora do repo) confirmou, contra um workspace real já gerado neste host: `ui.tree` lista a árvore, `ui.codemirror(...).disable()` bloqueia digitação de fato (testado clicando e digitando no editor), e a troca de linguagem por extensão funciona.
- `nicegui>=2.14` (já no `pyproject.toml`) inclui `ui.tree`, `ui.splitter` e `ui.codemirror` nativamente — nenhuma dependência nova.

## Goals / Non-Goals

**Goals:**
- Ler qualquer arquivo de texto do projeto gerado, com destaque de sintaxe, sem sair do portal.
- Garantir, de fato — não só visualmente — que o conteúdo não é editável.
- Reaproveitar o padrão de abas e de polling já estabelecido na página do sistema.

**Non-Goals:**
- Edição de arquivo (mesmo que o CodeMirror suporte; a aba nunca expõe isso).
- Visualizar o estado em um checkpoint específico — só o workspace atual. Se fizer falta, é extensão natural depois (reaproveitando `rollback`/`list_checkpoints` para resolver o SHA e o conteúdo via `git show`).
- Preview de binário (imagem, etc.) — mostra aviso, não tenta renderizar.
- Busca/filtro na árvore.

## Decisions

### D1 — Módulo novo `workspace_files.py`, sem NiceGUI

A listagem (filtro de diretórios técnicos, ordenação) e a leitura (decodificação, detecção de linguagem) vivem num módulo próprio, testável com `pytest` puro — sem subir UI nem Docker. `system_detail.py` só monta a UI em cima dele, no mesmo espírito de `checkpoints.py` (serviço) vs. `_render_checkpoints` (UI).

```python
# portal/appaiforge/workspace_files.py
IGNORED_DIRS = {".venv", "__pycache__", ".git", ".nicegui", "node_modules"}
EXT_LANGUAGE = {".py": "Python", ".toml": "TOML", ".lock": "TOML", ".json": "JSON", ...}

def project_dir(system) -> str: ...        # workspace_dir(system) + "/app"
def list_tree(system) -> list[dict]: ...    # nodes no formato do ui.tree
def read_file(system, rel_path: str) -> FileContent: ...  # texto + linguagem, ou "binário"
```

*Alternativa*: colocar a lógica direto em `system_detail.py` — descartada porque fica impossível testar sem levantar página NiceGUI, e o projeto já separa serviço de UI em todo o resto do arquivo (ver `checkpoints.py`, `gate.py`, `services/`).

### D2 — Escopo da árvore é `<workspace>/app`, não o workspace inteiro

O workspace do sistema também tem `portal_templates/`, `AGENTS.md`, `opencode.json`, `.git/` — não são "o projeto", são andaime da plataforma. A pasta `app/` é o que o supervisor sobe e o que o editor pediu para ver ("a pasta onde o projeto é criado").

*Risco aceito*: se o agente um dia gerar algo fora de `app/` (não é o padrão hoje — `agent-harness` exige "uma única app Python por sistema" dentro do workspace), o editor não vê. Revisitar se o padrão de geração mudar.

### D3 — Caminho relativo como `node_key`, não hash nem índice

Os nodes do `ui.tree` usam o caminho relativo a `app/` (ex.: `"main.py"`, `"templates/base.html"`) como `id`. É estável entre atualizações da árvore (um `refresh()` não invalida a seleção atual se o arquivo continuar existindo) e dá leitura direta: `read_file(system, node_id)` sem tabela de tradução.

*Risco*: caminho relativo com `..` ou absoluto, se viesse de fora, escaparia de `app/`. Mitigado: o `id` só se origina da própria árvore que o portal construiu (nunca de input livre do usuário), e `read_file` ainda normaliza e confere que o caminho resolvido fica dentro de `project_dir(system)` antes de abrir — defesa em profundidade, não a única barreira.

### D4 — Atualização por polling (`ui.timer`), como as outras abas

Em vez de um mecanismo novo de evento "execução terminou", a árvore se reconstrói a cada 2s enquanto a aba está montada — mesmo padrão de `_render_checkpoints`/`_render_gate_history`/`_render_usage`. Reconstruir a árvore é um `os.scandir` recursivo em `app/`, barato mesmo para um projeto gerado típico.

*Alternativa*: assinar os eventos de execução do `AgentQueue` (que já existe para o streaming do chat) e atualizar só quando um `run_finished` chegar — mais preciso, mas introduz acoplamento entre a aba Editor e o barramento de eventos do chat que nenhuma outra aba tem hoje. Fica para depois, se o polling custar caro na prática.

### D5 — Leitura de texto best-effort; binário vira aviso, não erro

`read_file` tenta `utf-8`; se falhar a decodificação (indício de binário), devolve um marcador em vez de lançar exceção ou mostrar bytes corrompidos. A UI mostra um card de aviso, no mesmo espírito do card de erro que `chat-artifacts` já usa para JSON inválido em blocos `echart`/`table` — consistente com o resto do portal, que nunca falha silenciosamente nem deixa o usuário sem explicação.

## Risks / Trade-offs

- **Árvore grande (muitos arquivos) deixa o poll de 2s perceptível** → mitigação natural: projetos gerados por este produto são uma app NiceGUI de porte modesto, não um monorepo; revisitar se isso deixar de ser verdade.
- **Arquivo gigante (ex.: um dump de dados deixado por engano) trava o painel ao renderizar** → `read_file` corta em um teto de tamanho (ex.: 1 MB) e avisa, em vez de tentar sempre o arquivo inteiro.
- **Concorrência**: o agente pode estar escrevendo um arquivo no exato momento em que o editor o abre → leitura parcial é possível; aceito como ruído de UI de leitura (não é dado persistido, só visualização), sem necessidade de lock.

## Open Questions

Nenhuma — as decisões acima resolvem tudo que mudaria o approach ou a lista de tarefas.
