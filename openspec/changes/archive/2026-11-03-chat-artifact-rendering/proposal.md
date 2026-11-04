# Proposal

## Why

O chat de geração atual exibe apenas texto e eventos de status do agente. Quando o editor pede ao agente que gere gráficos, tabelas ou visualizações, o resultado aparece como blocos de código sem renderização visual — o editor precisa abrir a app gerada para ver qualquer dado. Adicionar renderização de artifacts rich torna a conversa com o agente significativamente mais produtiva: gráficos e tabelas aparecem inline na resposta do agente, sem sair do chat.

## What Changes

- Nova função `parse_artifacts(text)` em `portal/appaiforge/ui/chat.py` que detecta fenced code blocks com linguagem `echart`, `table` ou `html` em respostas do agente e os renderiza com o componente NiceGUI correspondente.
- Suporte a três tipos de artifact:
  - **`echart`** — JSON de configuração Apache ECharts renderizado via `ui.echart`
  - **`table`** — JSON array de objetos renderizado via `ui.aggrid` com filtro e sort
  - **`html`** — HTML/SVG genérico renderizado em iframe sandboxed via `ui.html`
- Fallback de erro: quando o conteúdo do bloco é inválido (JSON malformado ou schema errado), exibe cartão de aviso com o conteúdo bruto colapsado — sem renderização silenciosa de lixo nem omissão do bloco.
- Atualização das guidelines globais (`AGENTS.md`) para instruir todos os agentes de sistema a usar os blocos especiais quando o editor pedir visualizações.
- O texto fora dos blocos continua sendo renderizado normalmente como markdown.

## Capabilities

### New Capabilities

- `chat-artifacts`: Capacidade do chat de detectar e renderizar blocos visuais estruturados (gráficos, tabelas, HTML) embutidos nas respostas do agente, com fallback explícito para conteúdo inválido.

### Modified Capabilities

- `agent-harness`: Adiciona requisito de que as guidelines da plataforma incluam instruções de formatação de artifacts visuais, de modo que o agente saiba produzir os blocos quando solicitado.

## Impact

- `portal/appaiforge/ui/chat.py` — função `render_event()`, nova função `parse_artifacts()`
- `portal/appaiforge/guidelines.py` — template do `AGENTS.md` com seção de artifacts
- Nenhuma mudança de schema de banco de dados
- Nenhuma mudança no harness opencode ou na fila de execução
