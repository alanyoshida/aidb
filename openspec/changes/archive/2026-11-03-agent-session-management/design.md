# Design

## Context

O portal mantém um `ChatSession` por usuário+sistema sem nome, e a cada `AgentRun` cria uma nova sessão no opencode via `POST /session`. O `harness_session_id` é salvo no `ChatSession` mas sobrescrito a cada execução. O modelo de dados já tem a coluna, falta a lógica de reutilização.

Eventos da run são persistidos em `RunEventRecord` para recuperação pós-F5. O chat UI já tem uma seção "Execuções anteriores" que lista as 10 últimas runs com seus eventos.

Três pontos de invalidação de sessão opencode:
1. `provision_system()` — recria o container (chamado por reconnect de BD, reconciliação, boot)
2. Crash do container sem restart do portal
3. Crash do processo opencode dentro do container

## Goals / Non-Goals

**Goals:**
- Múltiplas `ChatSession` nomeadas por usuário+sistema
- Reutilização do `harness_session_id` dentro de uma sessão (memória do agente)
- Aviso explícito "Contexto reiniciado" quando o harness_session fica inválido
- UI: lista de sessões, seletor, "Nova sessão", rename inline
- Título auto-gerado a partir do primeiro prompt (primeiras ~50 chars), renomeável

**Non-Goals:**
- Sessões compartilhadas entre usuários (cada usuário tem as suas)
- Reinjeção de histórico anterior ao criar nova sessão opencode (não sintético)
- Limite de número de sessões (sem max por ora)
- Sessões para `app_user` (apenas editores)

## Decisions

### D1 — Campo `context_reset` em `ChatSession`

`provision_system()` seta `context_reset = True` em todas as `ChatSession` do sistema
proativamente, antes de recriar o container. `_execute()` lê o flag:
- Se True → emite evento `session_context_reset` no buffer, cria nova sessão opencode, seta flag False e salva novo `harness_session_id`.
- Se harness_session_id inválido (404 detectado ao enviar prompt) → mesmo fluxo acima, sem ter lido o flag antes.

**Alternativa considerada**: campo `status` enum (`active | expired | closed`). Rejeitado por ser mais complexo que o necessário; `context_reset` bool + `harness_session_id nullable` cobre os estados relevantes.

### D2 — `enqueue()` aceita `chat_session_id` opcional

A UI passa o ID da sessão ativa ao enviar um prompt. `enqueue()` busca ou cria `ChatSession` por esse ID. Sem ID explícito, mantém comportamento atual (cria se não houver, usa a existente) para retrocompatibilidade com chamadas internas (reconciliação).

### D3 — Título gerado a partir do primeiro prompt

Ao criar `ChatSession`, o título é as primeiras 50 chars do prompt (sem cortar palavras), ex: `"Analise o schema da tabela pedidos e..."`. Editável depois via endpoint dedicado ou inline na UI.

### D4 — Detecção de sessão morta no harness

`OpencodeHarness.run()` já lida com `httpx.HTTPError`. Quando `POST /session/{id}/prompt_async` retorna 404, `run()` lança `SessionExpiredError` (nova exceção específica). `_execute()` captura, trata como `context_reset` e recria a sessão.

### D5 — Aviso de reinício como evento no buffer

O evento `session_context_reset` é inserido no buffer da run antes do `run_started`. O chat UI renderiza esse evento como um marcador visual na linha do tempo — mesmo mecanismo de `run_started`/`run_finished` — sem precisar de componente especial.

### D6 — `provision_system()` invalida sessões de forma proativa

Antes de recriar o container:
```python
with session_scope() as s:
    s.execute(
        update(ChatSession)
        .where(ChatSession.system_id == system.id)
        .values(context_reset=True, harness_session_id=None)
    )
```
Isso garante que mesmo que o portal não perceba o 404 (ex.: nenhum envio após o restart), a UI mostre o aviso na próxima mensagem.

## Risks / Trade-offs

| Risco | Mitigação |
|---|---|
| Container recriado enquanto run está em andamento | Run já falha com `httpx.HTTPError`; o run_error existente trata isso. O `context_reset` é setado antes de recriar, então a próxima run vê o flag. |
| Muitas sessões acumuladas por usuário | Sem paginação agora; limitar exibição a 20 sessões mais recentes na lista da UI sem deletar as antigas. |
| Título longo ou com caracteres especiais | Truncar em 100 chars no banco; UI trunca em 50 para exibição. |
| `harness_session_id` null race condition (dois workers concorrentes) | A fila já garante um worker por sistema; sem corrida no harness. |
