# Tasks

## 1. Modelo de dados — ChatSession

- [x] 1.1 Adicionar campos `title: Mapped[str | None]` (String(100), nullable) e `context_reset: Mapped[bool]` (default False) a `ChatSession` em `portal/appaiforge/models.py`, e remover qualquer constraint de unicidade `(system_id, user_id)` que impeça múltiplas sessões por usuário+sistema.
- [x] 1.2 Criar migration `portal/migrations/versions/<id>_chat_session_management.py` com `down_revision = 'f6a7b8c9d0e1'` que adiciona `title VARCHAR(100) NULLABLE` e `context_reset BOOLEAN NOT NULL DEFAULT FALSE` à tabela `chat_sessions`.

## 2. Harness — detecção de sessão morta

- [x] 2.1 Criar exceção `SessionExpiredError` em `portal/appaiforge/harness/base.py` (ou arquivo novo `portal/appaiforge/harness/errors.py`).
- [x] 2.2 Em `OpencodeHarness.run()` (`portal/appaiforge/harness/opencode.py`), detectar resposta HTTP 404 no `POST /session/{id}/prompt_async` e lançar `SessionExpiredError` em vez de `httpx.HTTPStatusError` genérico.

## 3. Fila — reutilização de sessão e reinício de contexto

- [x] 3.1 Em `AgentQueue.enqueue()` (`portal/appaiforge/agent_queue.py`), aceitar parâmetro `chat_session_id: str | None = None`; quando fornecido, buscar o `ChatSession` por ID em vez de criar/buscar pelo par `(system_id, user_id)`.
- [x] 3.2 Em `AgentQueue._execute()`, antes de chamar `harness.create_session()`, verificar se `ChatSession.harness_session_id` já está preenchido: se estiver, reutilizá-lo (não chamar `create_session()`). Caso `harness.run()` levante `SessionExpiredError`, tratar como reinício: emitir evento `session_context_reset` no buffer, criar nova sessão opencode, atualizar `harness_session_id` e continuar a execução.
- [x] 3.3 Em `AgentQueue._execute()`, ao iniciar a run, verificar `ChatSession.context_reset`: se True, emitir evento `session_context_reset` no buffer, chamar `harness.create_session()` para nova sessão, salvar novo `harness_session_id` e setar `context_reset = False` no banco, antes de enviar o prompt.
- [x] 3.4 Ao criar `ChatSession` com `title = None`, derivar o título automaticamente das primeiras 50 chars do prompt (sem cortar palavras), truncando em reticências se necessário, e salvar em `ChatSession.title`.

## 4. Provisionamento — invalidar sessões abertas

- [x] 4.1 Em `provision_system()` (`portal/appaiforge/provisioning.py`), antes do loop de remoção do container antigo, executar um `UPDATE chat_sessions SET context_reset = TRUE, harness_session_id = NULL WHERE system_id = <system.id>` para todas as sessões do sistema.

## 5. UI — gerenciamento de sessões no chat

- [x] 5.1 Em `portal/appaiforge/ui/chat.py`, adicionar painel lateral (ou seção acima do log) com a lista das últimas 20 sessões do usuário para o sistema atual, exibindo título e data de criação, com a sessão ativa destacada.
- [x] 5.2 Adicionar botão "Nova sessão" que chama um endpoint/service que cria uma nova `ChatSession` para o par `(system_id, user_id)` e a torna ativa na UI.
- [x] 5.3 Permitir rename inline do título da sessão ativa: clique no título abre input de edição; ao confirmar, atualiza `ChatSession.title` no banco.
- [x] 5.4 Ao trocar de sessão no painel, carregar e exibir o histórico de `AgentRun`s daquela sessão (eventos persistidos em `RunEventRecord`), substituindo o log atual.
- [x] 5.5 Adicionar renderização do evento `session_context_reset` no `render_event()`: exibir marcador visual "Contexto do agente reiniciado (container recriado)" na linha do tempo do chat, com ícone e cor distintos (ex.: ícone `refresh`, cor âmbar).
- [x] 5.6 Ao enviar um prompt (`do_send()`), passar o ID da sessão ativa para `queue.enqueue()` (novo parâmetro `chat_session_id`).

## 6. Testes

- [x] 6.1 Adicionar teste unitário em `portal/tests/unit/` verificando que `_execute()` reutiliza `harness_session_id` existente quando disponível (não chama `create_session()` de novo).
- [x] 6.2 Adicionar teste verificando que, quando `context_reset = True`, `_execute()` emite evento `session_context_reset` e cria nova sessão opencode.
- [x] 6.3 Adicionar teste verificando que `provision_system()` seta `context_reset = True` e nulifica `harness_session_id` em todas as `ChatSession` do sistema antes de recriar o container.
