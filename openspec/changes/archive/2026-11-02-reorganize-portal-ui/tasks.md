# Tasks

## 1. Chat em bolhas (`portal/appaiforge/ui/chat.py`)

- [x] 1.1 Substituir `render_event` (que hoje faz `ui.label(f"{icon} {label}")`) por uma renderização via `ui.chat_message`, seguindo a tabela de mapeamento da design.md (mensagem do usuário com `sent=True, name="Você"`; `message`/`file_edited`/`command_run`/eventos de gate com `sent=False`; `run_started`/`run_finished`/`run_interrupted`/`run_error` continuam como marcador compacto fora da bolha, não viram `chat_message`). Preservar literalmente o texto de cada evento (`event.text`, incluindo prefixos como `"bloqueada pelo gate:"`, `"aprovada pelo editor:"`). Verificar com `python3 -m py_compile portal/appaiforge/ui/chat.py` e com `grep -n 'data-testid=chat-input\|data-testid=chat-send\|data-testid=chat-interrupt' portal/appaiforge/ui/chat.py` confirmando que os três continuam presentes.
- [x] 1.2 Envolver o log do chat (run corrente) num `ui.scroll_area` de altura fixa; aplicar o mesmo mapeamento de `_load_run_events` (histórico persistido de `run_events`) às execuções anteriores dentro de cada `ui.expansion`. Verificar com `grep -n 'ui.scroll_area\|ui.chat_message' portal/appaiforge/ui/chat.py` e `python3 -m py_compile`.
- [x] 1.3 Manter `_render_approval` (painel de aprovação do gate) com seus `data-testid=gate-approve`/`data-testid=gate-deny` funcionando dentro da nova estrutura do chat. Verificar com `grep -n 'data-testid=gate-approve\|data-testid=gate-deny' portal/appaiforge/ui/chat.py`.

## 2. Abas na página do sistema (`portal/appaiforge/ui/system_detail.py`)

- [x] 2.1 Introduzir `ui.tabs()`/`ui.tab_panels()` com 4 abas (`chat` como `value` inicial — deve ser a primeira/padrão): Chat (ícone, ex. `"chat"`), Conexões (`"storage"`), Checkpoints (`"history"`), Auditoria (`"shield"`). Manter o cabeçalho atual (nome, badge de status, `/slug`, provedor/modelo, botões "Abrir app"/"Arquivar sistema"/"Excluir definitivamente") fixo acima das abas, sem alterar seus `data-testid`. Verificar com `python3 -m py_compile portal/appaiforge/ui/system_detail.py` e `grep -n 'data-testid=open-app\|data-testid=archive-system\|data-testid=delete-system' portal/appaiforge/ui/system_detail.py`.
- [x] 2.2 Mover a seção "Conexões de banco" (lista + formulário `add_conn`) para dentro do painel da aba "Conexões", preservando todos os `data-testid=conn-*` e `data-testid=save-connection`. Verificar com `grep -n 'data-testid=conn-\|data-testid=save-connection' portal/appaiforge/ui/system_detail.py`.
- [x] 2.3 Reescrever `_render_checkpoints` para usar `ui.timeline()`/`ui.timeline_entry(title=sha[:8], body=...)` com o botão "Restaurar" dentro de cada entrada, dentro do painel da aba "Checkpoints". Verificar com `grep -n 'ui.timeline' portal/appaiforge/ui/system_detail.py` e `python3 -m py_compile`.
- [x] 2.4 Unir `_render_gate_history` e `_render_usage` no painel da aba "Auditoria" (seções "Gate de destrutivas" e "Uso de tokens" lado a lado ou empilhadas), preservando os textos literais `"Gate de destrutivas"`, `"[bloqueada]"`/`"[aprovada]"`/`"[recusada]"` e `"Uso de tokens"` usados pelos testes E2E. Verificar com `grep -n 'Gate de destrutivas\|Uso de tokens' portal/appaiforge/ui/system_detail.py`.
- [x] 2.5 Rodar o portal localmente (`cd deploy && docker compose up -d --build portal`) e conferir manualmente no navegador: as 4 abas trocam de conteúdo, o chat em bolhas funciona com uma pergunta real em modo fake, o checkpoint existente aparece na timeline, e Conexões/Auditoria mostram os dados reais do sistema Homologacao.

## 3. Lista de sistemas (`portal/appaiforge/ui/systems.py`)

- [x] 3.1 Adicionar `icon="add"` ao botão "Novo sistema" e um ícone por card de sistema (ex. `"dns"` ou `"apps"`), mantendo a navegação `on_click`/`.on("click", ...)` existente. Verificar com `python3 -m py_compile portal/appaiforge/ui/systems.py` e checagem visual rápida na lista de sistemas no navegador.

## 4. Administração (`portal/appaiforge/ui/admin.py`)

- [x] 4.1 Adicionar `icon=` às abas já existentes `ui.tab("Usuários")`/`ui.tab("Grupos")` (ex. `"people"`/`"group"`) e aos botões de ação (`"Criar usuário"`, `"Criar grupo"`, `"Adicionar"`, `"Vincular"`), preservando todos os `data-testid` (`new-user-*`, `create-user`, `new-group-name`, `create-group`, `member-*`, `add-member`, `link-*`, `link-system`). Verificar com `python3 -m py_compile portal/appaiforge/ui/admin.py` e `grep -n 'data-testid=' portal/appaiforge/ui/admin.py` comparando com a lista anterior ao commit.

## 5. Atualizar testes E2E para navegação por abas

- [x] 5.1 Em `portal/tests/e2e/test_chat.py` e `portal/tests/e2e/test_full_journey.py`, trocar o `wait_for` de `"Conexões de banco"` dentro de `_wait_system_active` por `page.get_by_role("tab", name="Chat").wait_for(...)` (a aba fica visível independente de estar ativa). Verificar com `grep -n 'Conexões de banco' portal/tests/e2e/test_chat.py portal/tests/e2e/test_full_journey.py` confirmando que não sobrou nenhuma ocorrência fora do necessário.
- [x] 5.2 Em `portal/tests/e2e/test_systems.py` (2 ocorrências) e `portal/tests/e2e/test_gate.py` (`_create_system`), aplicar a mesma troca do passo 5.1; em `test_systems.py`, adicionar um clique na aba "Conexões" antes de `_fill_connection`. Verificar com o mesmo `grep` do passo 5.1 nesses dois arquivos.
- [x] 5.3 Em `portal/tests/e2e/test_gate.py`, adicionar `page.get_by_role("tab", name="Auditoria").click()` antes das três asserções que hoje esperam `"Gate de destrutivas"`/`"[bloqueada]"`/`"[aprovada]"` sem navegação. Verificar com `grep -n 'Gate de destrutivas\|\[bloqueada\]\|\[aprovada\]' portal/tests/e2e/test_gate.py` lendo o contexto ao redor para confirmar o clique foi inserido antes de cada uma.
- [x] 5.4 Em `portal/tests/e2e/test_full_journey.py`, adicionar `page.get_by_role("tab", name="Checkpoints").click()` antes de `page.get_by_text("Checkpoints").wait_for(...)` + clique em "Restaurar". Verificar com `grep -n 'Checkpoints' portal/tests/e2e/test_full_journey.py` lendo o contexto.

## 6. Verificação de integração

- [x] 6.1 Subir o stack E2E dedicado (`docker compose -f deploy/docker-compose.e2e.yml up -d --build`) e rodar `cd portal && uv run pytest tests/e2e/test_chat.py tests/e2e/test_systems.py tests/e2e/test_gate.py tests/e2e/test_full_journey.py` — os 4 arquivos tocados pela reorganização devem passar sem nenhuma outra alteração além das feitas no grupo 5.
- [x] 6.2 Rodar a suíte completa de unitários e BDD (`cd portal && uv run pytest tests/unit tests/bdd`) para confirmar que nada fora da UI foi afetado (esperado: nenhuma mudança de resultado, já que esta change não toca lógica de negócio).

## 7. Consistência de UI (rodada de polimento)

- [x] 7.1 `admin.py`: restaurar a criação da tabela de usuários (a reorganização anterior removeu `table = ui.table(...)`, deixando `refresh()` com `NameError`) e posicionar o botão "Novo usuário" **acima** da tabela; manter Ativo como "Sim"/"Não". Verificar com `grep -n 'ui.table' portal/appaiforge/ui/admin.py` e `python3 -m py_compile`.
- [x] 7.2 `admin.py`: mover o bloco de botões de Grupos ("Novo grupo"/"Adicionar membro a um grupo"/"Vincular a sistema") para **acima** da lista de grupos e adicionar empty state "Nenhum grupo ainda." quando não houver grupos. Verificar visualmente e com `grep -n 'Nenhum grupo ainda' portal/appaiforge/ui/admin.py`.
- [x] 7.3 `admin.py`: desambiguar rótulos — título do diálogo e botão de disparo "Adicionar membro a um grupo", confirmação "Adicionar ao grupo", confirmação "Vincular ao sistema"; preservar os `data-testid` (`member-*`, `add-member`, `link-*`, `link-system`).
- [x] 7.4 `system_create.py`: largura cheia (`w-full`) nos campos, em especial no select "Provedor de LLM" (label truncado), e `icon="add"` no botão "Criar sistema". Verificar com `python3 -m py_compile`.
- [x] 7.5 `guidelines_admin.py`: `icon="save"` no botão "Salvar".
- [x] 7.6 `system_detail.py` (Uso de tokens): agrupar por `run_id` (execução), unindo as linhas com `AgentRun.prompt` e e-mail do autor, com barra de peso relativo ao total; manter literal o texto `"total: N entrada / N saída"` usado pelo E2E. Verificar com `python3 -m py_compile`.
- [x] 7.7 Atualizar `portal/tests/e2e/test_admin_users.py` e `test_full_journey.py` para o novo nome do botão "Adicionar membro a um grupo".
- [x] 7.8 Corrigir regressões de E2E expostas por esta rodada: `test_systems.py` e `test_full_journey.py` passam a abrir o diálogo "Nova conexão" antes de preencher; `_select` espera o menu anterior fechar (o grupo e o slug de mesmo nome em `test_full_journey` selecionavam o item errado). Rodar `tests/e2e` (11 testes) verde.

## Workflow follow-up

- Arquivar esta change (`/opsx:archive reorganize-portal-ui`) depois que as tasks acima estiverem concluídas e revisadas.
