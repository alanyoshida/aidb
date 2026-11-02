# Tasks

Convenções herdados do projeto: três camadas de teste (unitários, BDD a partir dos cenários das specs, E2E Playwright — ADR 0016) e decisão nova vira ADR sequencial (esta change gera o ADR 0017 com a política DDL-bloqueado/DML-confirmado, sqlglot e auto-aprovação).

## 1. Classificador canônico (sqlglot)

- [x] 1.1 Adicionar `sqlglot` às dependências do portal e da imagem base, e implementar `appaiforge/app_template/sqlgate.py` com `classify(sql) -> Normal | Confirmable(reason) | Blocked(reason)` cobrindo: DDL bloqueada, DELETE/UPDATE sem WHERE restritivo confirmável, DML por chave normal, múltiplas statements com pior classe; verificar com testes unitários o catálogo de escapes (comentários, CTEs, `OR 1=1`, subqueries, caixa alta/baixa, múltiplas statements)
- [x] 1.2 Criar a migração Alembic da tabela `gate_decisions` (origem, sql, connection_name, classificação, decisão, author_id, run_id, created_at) e o serviço de registro/consulta do gate; verificar que `alembic upgrade head` cria a tabela e que os testes unitários do serviço registram e listam decisões
- [x] 1.3 Validar a cópia do `sqlgate.py` incorporada nas guidelines contra o módulo original (teste que garante que não divergem) e verificar que `AGENTS.md`/guidelines passam a exigir a camada

## 2. Gate do agente (permissões do opencode)

- [x] 2.1 Executar o spike do fluxo de permissões do opencode 1.19.5: configuração de `permission` no `opencode.json` (bash patterns + ferramentas MCP), formato dos eventos de pedido no `/event` e payload do endpoint de reply (v1/v2); registrar o mapeamento no design.md
- [x] 2.2 Estender o `write_opencode_config` do provisionamento com o permissionamento do gate (bash SQL + ferramentas MCP de escrita em `ask`) e verificar em container real que um `DELETE` sem WHERE dispara pedido de permissão
- [x] 2.3 Estender o adapter `OpencodeHarness` com eventos de pedido de permissão normalizados (`gate_request`) e o reply (aprovar/recusar), com testes unitários contra o servidor falso cobrindo pedido, aprovação, recusa e recusa automática de bloqueadas
- [x] 2.4 Implementar o serviço de decisão no portal: pedido do harness → classificador D1 → recusa automática de bloqueadas / pendência para confirmáveis / aprovação automática de normais, com auditoria de cada decisão; verificar com testes unitários os três caminhos e o registro
- [x] 2.5 Adicionar o estado `aguardando aprovação` ao run na fila (visível na fila e no chat; interromper a run recusa o pedido pendente) e verificar com testes que a fila reflete o estado e que interromper resolve o pedido como recusado

## 3. Aprovação no chat

- [x] 3.1 Renderizar no chat o pedido de aprovação (SQL, conexão, classificação, contagem estimada quando disponível) com botões aprovar/recusar, consumindo os eventos do buffer da run; verificar com suíte E2E Playwright (harness fake estendido com cenário de gate): pedido aparece, aprovação destrava a run, recusa notifica o agente e a run continua
- [x] 3.2 Exibir a seção "Gate" na página do sistema com o histórico de decisões (autor, SQL, conexão, decisão, data) para editores e admins; verificar com E2E que aprovação e bloqueio automático aparecem no histórico

## 4. Gate na app gerada

- [x] 4.1 Implementar `appaiforge/app_template/dbgate.py` (pool asyncpg embrulhado, `GateConfirmationRequired` com contagem estimada via `SELECT count(*)`, `GateBlocked`) com testes unitários das três classes contra Postgres efêmero
- [x] 4.2 Atualizar as guidelines para tornar a camada obrigatória (com exemplo de diálogo de confirmação na UI) e o provisionamento para garantir `sqlglot` no venv da app gerada; verificar em sessão manual que uma app gerada nova nasce com a camada e que a atualização de guidelines propaga (migração de apps antigas na próxima edição)
- [x] 4.3 Verificar em app real gerada pelo agente (sessão manual, `@llm_real`): DELETE em massa pela UI dispara o diálogo com contagem e só executa após confirmação; DDL é recusado com mensagem

## 5. Verificação ponta a ponta

- [x] 5.1 Estender a suíte E2E (harness fake com evento de gate): pedido do agente → TRUNCATE recusado automaticamente (sem botão) e DELETE em massa aprovado no chat executa e audita; verificar verde do zero
- [x] 5.2 Atualizar o README (seção "Gate de operações destrutivas": classes, aprovação no chat, confirmação na app, auditoria) e verificar que um operador entende o comportamento lendo apenas o documento

## Workflow follow-up

- Gerar o ADR 0017 (política do gate: DDL bloqueado, DML confirmável, sqlglot, auto-aprovação registrada) durante a implementação.
- Após implementação concluída e revisada: `/opsx:archive`.
