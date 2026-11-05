# Tasks

## 1. Serviço de arquivos do workspace

- [ ] 1.1 Criar `portal/appaiforge/workspace_files.py` com `project_dir(system)` (`workspace_dir(system)/app`, reaproveitando `checkpoints.workspace_dir`) e `list_tree(system)` (árvore recursiva no formato de nodes do `ui.tree`, ignorando `.venv`, `__pycache__`, `.git`, `.nicegui`, `node_modules` e diretórios vazios após o filtro); verificar com teste unitário que a árvore reflete a estrutura real de um `tmp_path` e que os diretórios técnicos não aparecem
- [ ] 1.2 Implementar `read_file(system, rel_path)`: resolve o caminho dentro de `project_dir(system)`, recusa escapar dessa pasta, lê como UTF-8 com teto de tamanho (1 MB), e devolve um marcador de "binário/ilegível" em vez de lançar exceção quando a decodificação falha; verificar com testes unitários os três casos — texto normal, arquivo binário, caminho tentando escapar com `..`
- [ ] 1.3 Implementar detecção de linguagem por extensão (`EXT_LANGUAGE`, mapeando para os valores aceitos por `ui.codemirror.SUPPORTED_LANGUAGES`) com `None` para extensão desconhecida; verificar com teste unitário `.py`→Python, `.toml`/`.lock`→TOML, extensão desconhecida→`None`

## 2. Aba Editor na página do sistema

- [ ] 2.1 Adicionar `editor_tab = ui.tab("editor", label="Editor", icon="code")` logo após `chat_tab` em `system_detail.py` com `data-testid=tab-editor`, e o `ui.tab_panel` correspondente chamando `_render_editor(system, user)`, dentro do mesmo bloco já restrito a `can_manage_system`; verificar com o teste E2E da task 2.5 que a aba aparece
- [ ] 2.2 Implementar `_render_editor(system, user)`: `ui.splitter` com `ui.tree` (`data-testid=editor-tree`, a partir de `workspace_files.list_tree`) à esquerda e `ui.codemirror(...).disable()` (`data-testid=editor-content`) à direita; estado inicial com instrução para selecionar um arquivo; verificar com o teste E2E da task 2.5
- [ ] 2.3 Tratar a árvore vazia (projeto ainda não gerado) com uma mensagem explícita (`data-testid=editor-empty`) em vez de uma árvore em branco; verificar com teste unitário de `list_tree` que ele devolve lista vazia quando `app/` não existe, e com o teste E2E da task 2.5 que a mensagem aparece antes da primeira geração
- [ ] 2.4 Tratar o retorno de "binário/ilegível" de `read_file` exibindo um card de aviso (`data-testid=editor-binary-warning`) no lugar do editor, no mesmo estilo dos cards de erro de `chat-artifacts`; verificar com teste unitário de `workspace_files.read_file` contra um arquivo binário de fixture
- [ ] 2.5 Criar `tests/e2e/test_workspace_viewer.py`: cria sistema, confirma a mensagem de árvore vazia antes de qualquer geração, envia um pedido no chat (harness fake grava `app/main.py` deterministicamente — ver `harness/fake.py`), abre a aba Editor, seleciona `main.py` na árvore e confirma que o conteúdo aparece no painel; tenta digitar no painel e confirma que o conteúdo não muda; verificar rodando `uv run pytest tests/e2e/test_workspace_viewer.py` contra o stack E2E

## 3. Atualização automática

- [ ] 3.1 Adicionar `ui.timer(2.0, refresh_tree)` à aba Editor, reconstruindo a árvore a partir de `workspace_files.list_tree`, preservando a seleção atual quando o arquivo continuar existindo (por `node_key`/caminho relativo estável — D3); estender o teste E2E da task 2.5 para disparar um segundo pedido no chat, que grava um segundo arquivo, e confirmar que ele aparece na árvore sem recarregar a página

## 4. Documentação

- [ ] 4.1 Atualizar a seção "Chat" do `README.md` (ou criar uma seção "Editor" ao lado dela) descrevendo a aba nova — somente leitura, reflete o workspace atual; verificar lendo a seção que ela descreve o comportamento implementado

## Workflow follow-up

- Arquivar a change após a revisão, sincronizando os deltas para `openspec/specs/`.
- Verificar o resultado arquivado: `workspace-viewer` existe como spec vigente.
