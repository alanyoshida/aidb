# Proposal

## Why

Cada mensagem enviada ao agente hoje cria uma nova sessão no opencode, zerando o contexto a cada envio. Editores que trabalham iterativamente num sistema precisam re-explicar decisões já tomadas na mesma sessão de trabalho, e não há como retomar uma conversa anterior ou organizar o trabalho em múltiplas frentes paralelas.

## What Changes

- `ChatSession` passa a suportar múltiplas sessões nomeadas por usuário+sistema (atualmente é uma por usuário+sistema, sem nome).
- O `harness_session_id` do opencode é reutilizado dentro de uma sessão, dando ao agente memória das mensagens anteriores.
- Quando o container é recriado (`provision_system`), as sessões existentes têm o contexto marcado como reiniciado; a próxima mensagem exibe um aviso explícito antes de criar uma nova sessão opencode.
- Se o `harness_session_id` estiver inválido por outro motivo (crash do container), o mesmo fluxo de aviso é acionado ao detectar o erro 404.
- A UI do chat ganha um painel lateral de sessões com seletor, botão "Nova sessão" e rename inline.
- O título da sessão é gerado automaticamente a partir das primeiras palavras do primeiro prompt e pode ser renomeado pelo editor.

## Capabilities

### New Capabilities

_(nenhuma nova capability; os requisitos de sessão pertencem à capability existente `agent-harness`)_

### Modified Capabilities

- `agent-harness`: adiciona requisitos de sessões nomeadas múltiplas, continuidade de contexto dentro da sessão e aviso explícito de reinício de contexto.

## Impact

- **`portal/appaiforge/models.py`**: `ChatSession` recebe campos `title` (string nullable) e `context_reset` (bool, default False); constraint de unicidade `(system_id, user_id)` é removida para permitir múltiplas sessões.
- **`portal/alembic/`**: migração para adicionar `title` e `context_reset` à tabela `chat_sessions`.
- **`portal/appaiforge/agent_queue.py`**: `enqueue()` aceita `chat_session_id` opcional para usar sessão existente; `_execute()` reutiliza `harness_session_id` quando disponível, detecta 404 e aciona o fluxo de reinício.
- **`portal/appaiforge/provisioning.py`**: `provision_system()` marca `context_reset = True` em todas as `ChatSession` do sistema antes de recriar o container.
- **`portal/appaiforge/harness/opencode.py`**: detecta 404 ao enviar prompt em sessão morta e sinaliza reinício ao chamador.
- **`portal/appaiforge/ui/chat.py`**: painel de sessões (lista, seletor, "Nova sessão", rename inline), aviso de reinício de contexto na linha do tempo do chat.
