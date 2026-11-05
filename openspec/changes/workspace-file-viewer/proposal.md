# Proposal

## Why

Hoje a única forma de ver o código que o agente gerou é abrir a app publicada ou acessar o container por fora do portal. O editor acompanha o resultado do trabalho pelo texto das mensagens do chat e pela lista de arquivos alterados (quando o modo debug está ligado), mas não tem como abrir um arquivo específico e ler o código com destaque de sintaxe, sem sair do portal e sem risco de editar por engano o que o agente produziu. Um protótipo validado nesta sessão mostrou que o NiceGUI já tem os componentes necessários (`ui.tree`, `ui.splitter`, `ui.codemirror`), então o custo de entregar isso é baixo.

## What Changes

- Nova aba **Editor** na página do sistema, ao lado da aba Chat, com os mesmos usuários e a mesma condição de acesso das abas já existentes (Chat, Conexões, Checkpoints, Configurações, Auditoria).
- A aba mostra, à esquerda, uma árvore com os arquivos da pasta onde o agente gera o projeto (`<workspace>/app`), ignorando artefatos técnicos (`.venv`, `__pycache__`, caches do NiceGUI); à direita, o conteúdo do arquivo selecionado, com destaque de sintaxe pela extensão.
- O conteúdo é **somente leitura**: o editor nunca aceita edição, e nenhuma ação desta aba grava no workspace do sistema.
- A árvore reflete o estado atual do workspace (não o de um checkpoint específico) e se atualiza por si só quando o agente termina uma execução, para o editor ver o resultado sem precisar trocar de aba e voltar.

Fora de escopo desta change: edição de arquivos, visualização de versões anteriores por checkpoint, preview de arquivos binários (imagens), e busca/filtro na árvore — ficam para uma iteração futura se fizerem falta.

## Capabilities

### New Capabilities
- `workspace-viewer`: permite que editores com acesso de gestão ao sistema naveguem e leiam, sem editar, os arquivos que o agente gerou no workspace, com destaque de sintaxe por linguagem

## Impact

- `portal/appaiforge/ui/system_detail.py`: nova aba e painel `_render_editor(system, user)`, seguindo o padrão das abas existentes
- `portal/appaiforge/workspace_files.py` (novo): listagem da árvore de arquivos e leitura de conteúdo, isolado da UI para ser testável sem NiceGUI
- `portal/tests/unit/`: unitários de `workspace_files.py` (filtragem de ruído, detecção de linguagem, arquivo binário, teto de tamanho) — mesmo nível de cobertura que `chat-artifacts` (`test_chat_artifacts.py` testa `parse_artifacts`/lógica pura, não a renderização NiceGUI)
- `portal/tests/e2e/test_workspace_viewer.py` (novo): cobertura ponta a ponta da aba, no mesmo padrão Playwright de `test_chat.py`/`test_systems.py`, usando o harness fake (determinístico) para gerar arquivo real
- Sem mudança de dados, de API externa, nem de dependência (`ui.tree`/`ui.splitter`/`ui.codemirror` já vêm no `nicegui` que o projeto usa)
