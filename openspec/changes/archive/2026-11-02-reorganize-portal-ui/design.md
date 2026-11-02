# Design

## Context

Ver `proposal.md` — `system_detail.py` empilha 6 seções numa `ui.page` só; `chat.py` renderiza eventos com `ui.label` cru. `admin.py` já usa `ui.tabs()`/`ui.tab_panels()` (abas "Usuários"/"Grupos"), então o padrão de abas já existe no projeto, só não chegou em `system_detail.py`.

NiceGUI 3.18 (já instalado, confirmado em `portal/.venv`) fornece os componentes usados aqui:
- `ui.tabs()` / `ui.tab(name, label=, icon=)` / `ui.tab_panels(tabs, value=, keep_alive=True por padrão)` / `ui.tab_panel(name)`
- `ui.chat_message(text=, name=, stamp=, avatar=, sent=, text_html=)` — componente Quasar `q-chat-message`
- `ui.scroll_area(on_scroll=)`
- `ui.timeline(side=, layout=, color=)` / `ui.timeline_entry(body=, title=, subtitle=, icon=, tag=)` — Quasar `q-timeline`
- `ui.button(icon=)` / `ui.icon(name)` — ícones são nomes do Material Icons (a fonte já vem embutida no NiceGUI; `chat.py` já usa `icon="history"` num `ui.expansion`, então o mecanismo já está em uso no projeto)

Validado via mockup interativo (artifact de design) antes desta change: https://claude.ai/artifact/QXfFmrLNVQPY3jo9hDQTHn — o usuário aprovou a estrutura de abas e o chat em bolhas.

## Goals / Non-Goals

**Goals:**
- Reorganizar `system_detail.py` em abas com `ui.tabs()`/`ui.tab_panels()`, sem perder nenhuma funcionalidade existente (refresh em tempo real via `ui.timer`, formulário de conexão, aprovação do gate, restaurar checkpoint, arquivar/excluir sistema).
- Trocar o log do chat por `ui.chat_message` preservando literalmente o texto de cada evento (necessário para os testes E2E, que fazem `get_by_text` em substrings como `"bloqueada pelo gate"`, `"PEDIDO DE APROVAÇÃO"`, `"aprovada pelo editor"`, `"agente livre"`).
- Preservar todos os `data-testid` existentes nos elementos que os têm hoje (`chat-input`, `chat-send`, `chat-interrupt`, `gate-approve`, `gate-deny`, `archive-system`, `delete-system`, `conn-*`, `save-connection`).
- Atualizar os testes E2E que dependiam de conteúdo estar sempre visível na mesma rolagem, para navegar à aba correta antes de cada asserção.

**Non-Goals:**
- Não muda nenhum comportamento do agente, do gate, de conexões ou de autenticação — só a apresentação.
- Não introduz um sistema de design (tokens, tema customizado) — usa o tema padrão do NiceGUI/Quasar já em uso.
- Não migra `login.py`, `system_create.py` nem `guidelines_admin.py` (páginas pequenas e já sem o problema de empilhamento) — fora do escopo desta change.

## Decisions

### 1. Abas com `keep_alive=True` (padrão do NiceGUI) em vez de `keep_alive=False`

`ui.tab_panels` usa Vue `keep-alive` por padrão: painéis inativos continuam montados no servidor, só ficam ocultos no cliente. Isso significa que os `ui.timer` de refresh já existentes (`refresh_conns`, `refresh_cps`/checkpoints, `refresh_gate`, `refresh_usage`, e os timers do chat) continuam rodando normalmente mesmo com a aba não selecionada — **nenhuma mudança de lógica de polling é necessária**, só a reorganização visual. Alternativa considerada: criar os painéis sob demanda (lazy, só ao clicar na aba) — rejeitada porque exigiria reescrever a lógica de refresh de cada seção e não traz benefício aqui (o portal já tolera N timers de 2s por sistema aberto).

### 2. Estrutura de abas: Chat (padrão) · Conexões · Checkpoints · Auditoria

Chat como aba padrão porque é o fluxo principal (criar/editar a app) e porque isso **preserva os testes E2E que já assumem que o chat está imediatamente visível** após abrir a página do sistema (`chat-input`/`chat-send` sem nenhum clique de navegação). "Auditoria" une Gate de destrutivas + Uso de tokens (ambos read-only, consultados com pouca frequência) — decisão já validada com o usuário na exploração.

### 3. Eventos do chat → `ui.chat_message`, mapeamento por tipo

| `event.kind` | Render | `sent` |
|---|---|---|
| mensagem do usuário (prompt enviado) | `ui.chat_message(text=prompt, name="Você")` | `True` |
| `message` | `ui.chat_message(text=event.text, name="Agente")` | `False` |
| `file_edited`, `command_run` | `ui.chat_message` com `name` indicando o tipo (ex. "arquivo alterado", "comando") + `ui.icon` correspondente | `False` |
| `gate_request`, `gate_denied`, `gate_approved`, `gate_resolved` | `ui.chat_message` com cor de fundo diferenciada (classes Tailwind já usadas hoje: laranja/vermelho/verde) | `False` |
| `run_started`, `run_finished`, `run_interrupted`, `run_error` | status compacto fora da bolha (label pequeno centralizado, como hoje), não vira `chat_message` — são marcadores de transição, não conteúdo de conversa | — |
| `tool_output`, `usage` | continuam fora do chat (`_QUIET_KINDS`, sem mudança) | — |

O texto de cada evento (`event.text`, incluindo os textos fixos como `"bloqueada pelo gate: ..."`, `"liberada pelo gate: ..."`, `"aprovada pelo editor: ..."`) **não muda** — só o componente que o envolve. O painel de aprovação do gate (`_render_approval`) continua como está hoje (card com SQL + botões Aprovar/Recusar e seus `data-testid`), só passa a viver dentro do `ui.scroll_area` do chat.

O histórico de execuções anteriores (`_load_run_events`, já persistido em `run_events`) usa o mesmo mapeamento acima dentro de cada `ui.expansion` por execução.

### 4. Checkpoints → `ui.timeline`

Cada `ui.timeline_entry(title=sha[:8], body=message, icon="commit")` com o botão "Restaurar" dentro do `body` (NiceGUI permite elementos filhos dentro de um timeline entry via `with`). Alternativa considerada: manter `ui.list`/`ui.item` (mais simples) — rejeitada porque o usuário já validou a timeline no mockup.

### 5. Testes E2E: trocar o sinal de "página do sistema carregou"

Hoje, dois helpers (`_wait_system_active` em `test_chat.py` e `test_full_journey.py`) e três chamadas inline (`test_systems.py` ×2, `test_gate.py` ×1) esperam o texto `"Conexões de banco"` aparecer para confirmar que a página do sistema renderizou, antes de continuar (poll de badge `ativo`/`erro`, ou preencher o formulário de conexão). Com `"Conexões de banco"` escondido dentro de uma aba inativa, esse `wait_for` (que por padrão exige elemento **visível**) vai dar timeout.

- Nos dois helpers `_wait_system_active`, trocar o `wait_for` para esperar a aba "Chat" (`page.get_by_role("tab", name="Chat")`), que está sempre visível ao carregar a página, independente de a aba estar ativa — o loop de poll do badge que já existe depois continua garantindo que o sistema ficou `ativo`.
- Em `test_systems.py` (onde o teste de fato preenche o formulário de conexão logo em seguida), trocar o `wait_for("Conexões de banco")` por um clique na aba "Conexões" antes de chamar `_fill_connection`.
- Em `test_gate.py`, antes das asserções de `"Gate de destrutivas"`/`"[bloqueada]"`/`"[aprovada]"`, clicar na aba "Auditoria".
- Em `test_full_journey.py`, antes de `page.get_by_text("Checkpoints").wait_for(...)` + clicar "Restaurar", clicar na aba "Checkpoints".

Não é necessário mudar nada em `test_chat.py:123` (`"Execuções anteriores".click()`) nem nas asserções de gate dentro do fluxo de chat (`"bloqueada pelo gate"`, `"PEDIDO DE APROVAÇÃO"`, `"aprovada pelo editor"`, `"agente livre"`) — tudo isso vive dentro da aba Chat, que é a aba padrão.

## Risks / Trade-offs

- **[Risco]** Testes E2E que assumem conteúdo sempre visível na mesma rolagem quebram ao mover esse conteúdo para abas inativas por padrão (`wait_for` com estado `visible` nunca resolve). → **Mitigação**: lista exata de arquivos/linhas afetados identificada acima (decisão 5); tasks.md inclui a atualização desses 4 arquivos de teste como parte da própria change, não como débito técnico separado.
- **[Risco]** Se algum teste futuro (ou um humano usando a app) depender de ver duas seções ao mesmo tempo (ex.: SQL do gate + conexão correspondente lado a lado), abas tornam isso impossível sem alternar. → **Mitigação**: nenhum teste ou fluxo atual faz isso (confirmado por grep nos E2E); se surgir, é um ajuste de aba, não uma reversão da reorganização.
- **[Risco]** `ui.chat_message` escapa HTML por padrão (`text_html=False`) e insere `<br/>` para quebras de linha — comandos SQL longos ou saídas de comando com caracteres especiais (`<`, `>`, `&`) precisam continuar aparecendo como texto literal, não quebrar o escaping. → **Mitigação**: usar o comportamento padrão (`text_html=False`); não há necessidade de HTML nas mensagens, então o escape automático do componente é estritamente mais seguro que o `ui.label` atual (nenhuma mudança de risco de XSS, só uma melhoria).

## Migration Plan

Mudança é só de código de UI, sem estado persistido, sem migration de banco. Deploy é um rebuild normal do container `portal` (`docker compose up -d --build portal`), sem passo manual. Rollback é reverter o commit e rebuildar — nenhum dado é afetado.

Ordem de implementação sugerida (detalhada em `tasks.md`): `chat.py` primeiro (unidade mais isolada, maior ganho visual), depois a reestruturação em abas de `system_detail.py` (que já consome `render_chat`), depois `systems.py` e `admin.py` (ajustes pequenos e independentes), por fim os 4 arquivos de teste E2E afetados.
