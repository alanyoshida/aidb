# Design

## Context

O MVP está em produção interna: apps NiceGUI escrevem nos bancos das conexões com a credencial registrada (ADR 0015 — risco aceito à época, com o gate prometido como change seguinte) e o agente acessa os mesmos bancos via MCP. O opencode (1.19.5, pinado) tem fluxo nativo de **permissões** — pedidos chegam como eventos no `/event` e são respondidos via `POST /session/{id}/permission/{requestID}/reply` (spike 5.1) — e aceita configuração de permissões por ferramenta/padrão de comando no `opencode.json`. A app gerada acessa o banco via driver direto (asyncpg) orientado pelas guidelines (ADR 0011), que já materializam módulos canônicos do template (`app_template/identity.py` como precedência).

## Goals / Non-Goals

**Goals:**

- Um único classificador SQL (sqlglot) usado pelo portal (agente) e pelo template (app gerada) — mesma decisão nos dois caminhos.
- Agente: DDL recusado automaticamente; DML em massa vira pedido de aprovação no chat (auto-aprovação registrada); DML escopado flui sem atrito.
- App gerada: confirmação na UI com contagem estimada de linhas para operações confirmáveis; DDL recusado.
- Auditoria completa e visível.

**Non-Goals:**

- Credencial de banco restrita por schema/tabela (change própria).
- Outros bancos além de Postgres (o classificador é genérico em SQL, mas o gate só é provisionado hoje para as conexões Postgres existentes).
- Desfazer operações aprovadas; bloqueio de custo; permissões por papel na aprovação (auto-aprovação é a regra v1).

## Decisions

### D1 — Classificador único em sqlglot, compartilhado por portal e app

Módulo canônico `appaiforge/app_template/sqlgate.py`: `classify(sql) -> Normal | Confirmable | Blocked(reason)` usando sqlglot (parse Postgres). Regras: qualquer statement DDL (`DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`) → bloqueada; `DELETE`/`UPDATE` sem `WHERE`, com `WHERE` tautológico ou sem condição por linha → confirmável; DML com `WHERE` por chave → normal; múltiplas statements numa única string → pior classe entre elas. O portal importa o módulo diretamente; a app gerada recebe uma cópia via template (mesmo padrão do `identity.py`) — e o teste de unidade do portal valida a cópia das guidelines contra o módulo original (nada de divergência silenciosa). Alternativa descartada: regex (falha com CTEs/comentários/subqueries); executar classificação só no banco via `EXPLAIN` (não cobre DDL e não evita a execução).

### D2 — Gate do agente via sistema de permissões do opencode, decidido no portal

O `opencode.json` gerado no provisionamento passa a incluir configuração de permissões: padrões de bash que executam SQL (psql, `*.sql`) e as ferramentas MCP de escrita exigem permissão (`ask`). O adapter do harness passa a consumir os eventos de pedido de permissão do `/event`, classifica o SQL extraído do pedido com D1 e responde via endpoint de reply: `bloqueada` → recusa imediata automática; `confirmável` → fica pendente até a decisão no chat; `normal` → aprovação imediata automática (sem atrito). A classificação fica **no portal** — a app/agent nunca decide sozinho.

**Refinado no spike 2.1 (opencode 1.19.5, validado em container real):**
- Config: `"permission": {"bash": {"*": "allow", "<padrões SQL>": "ask"}}` — a última correspondência vence, wildcards `*`/`?`.
- Evento: `permission.asked` no `/event` com `properties = {id: "per_...", sessionID, permission: "bash", patterns: [...], metadata: {command: "<comando completo>"}, always: [...], tool: {messageID, callID}}` — o comando a classificar está em `metadata.command`.
- Reply: `POST /session/{sessionID}/permission/{requestID}/reply` com `{"response": "once"}` → 200 (aprova); recusa via resposta equivalente de rejeição (validar valor exato na implementação).
- **Limitação**: o permissionamento do opencode **não cobre ferramentas MCP** (chaves fixas: bash/edit/etc.). As escritas via MCP são fechadas de outra forma: o provisionamento troca o `server-postgres` genérico por um **MCP server próprio de leitura** (`gated-mcp`, Python, com o classificador canônico) que expõe apenas `list_tables`/`describe_table`/`read_query` — `read_query` recusa qualquer statement que não seja leitura pura (SELECT/EXPLAIN), logo **escritas via MCP são sempre recusadas**; a via de escrita do agente é o bash, que passa pelo fluxo de permissões acima. Assim as três classes da spec seguem observáveis no caminho bash e o caminho MCP é somente-leitura por construção.

Alternativa descartada: pedir para o agente "sempre consultar antes" via guidelines (política por prompt, não enforcement).

### D3 — Aprovação no chat como primeiro-class citizen da fila

Um run pode entrar em estado novo `aguardando aprovação` (visível na fila e no chat, como a execução corrente já é). O chat renderiza o pedido (SQL, conexão, contagem estimada quando calculável) com botões aprovar/recusar; a decisão viaja pelo mesmo canal do interrupt. Auto-aprovação: o editor que conduz a sessão decide sozinho — coerente com single-tenant (ADR 0014) — e tudo é auditado. Timeout do pedido: sem expiração automática na v1 (o run fica aguardando; o editor pode interromper a run, o que recusa o pedido pendente).

### D4 — Gate da app gerada como camada de acesso a dados obrigatória

Template `appaiforge/app_template/dbgate.py`: pool asyncpg embrulhado — `execute(sql)` classifica antes; `confirmável` levanta `GateConfirmationRequired(estimated_rows)` que a UI da app traduz no diálogo de confirmação (execução com token de confirmação emitido na mesma request); `bloqueada` levanta `GateBlocked`. Contagem estimada: `SELECT count(*)` com o mesmo WHERE (apenas para confirmáveis). As guidelines passam a exigir que **todo** acesso a banco na app gerada passe por essa camada (o provisionamento injeta `sqlglot` no venv da app — requisito novo do template; apps são geradas com ela desde a primeira geração). Apps já geradas antes desta change não são migradas automaticamente: a próxima edição pelo agente as converte (a guidelines instrui a migração).

### D5 — Auditoria em tabela própria, visível na página do sistema

Tabela `gate_decisions` (id, system_id, run_id nulo na app, origem `agente|app`, sql, connection_name, classificação, decisão `aprovada|recusada|bloqueada`, author_id nulo na app, created_at) — página do sistema ganha seção "Gate" com o histórico. Sem purge automático.

## Risks / Trade-offs

- [Fluxo de permissão do opencode difere do esperado (v1 vs v2, payload de reply)] → spike 1.1 antes do adapter; versão pinada isola o comportamento.
- [Falso positivo do classificador trava operação legítima] → DML escopado por PK é `normal`; decisões são auditadas e a recusa mostra o motivo; ajuste de regras é código revisado por teste, não config.
- [Falso negativo (SQL destrutivo classificado como normal)] → sqlglot parseia a statement real (não heurística textual); testes de classificação cobrem o catálogo de escapes (comentários, CTEs, `OR 1=1`, subqueries); camada extra: ferramentas MCP de escrita sempre pedem permissão — o portal decide, nunca o agente.
- [App antiga sem o gate] → mitigação consciente: a próxima edição pelo agente converte (guidelines); mudanças de código direto na app seguem sob responsabilidade do dono (mesma postura do ADR 0015).
- [Run do agente fica pendente indefinidamente aguardando aprovação] → visível na fila; interromper a run recusa o pendente; sem timeout automático na v1.

## Migration Plan

1. Merge das dependências (sqlglot no portal e na imagem base); migração Alembic da auditoria.
2. Spike do fluxo de permissões do opencode (1.1); adapter + gate do agente; UI de aprovação no chat.
3. Template `dbgate.py` + guidelines atualizadas; provisionamento injeta a dependência.
4. E2E: pedido de DELETE em massa via agente → aprovação no chat → execução auditada; TRUNCATE → recusa automática; app gerada com diálogo de confirmação.
5. Rollback: reverter deploy do portal e imagem base (tabela nova é aditiva; apps antigas continuam rodando).

## Open Questions

- Formato exato dos eventos de permissão do opencode e payload de reply — resolvido no spike 1.1 (sem impacto nas specs).
- Regras finais de fronteira do classificador (ex.: `INSERT ... SELECT` sem WHERE) — fechadas nos testes de classificação da implementação; a spec fixa apenas as três classes e os exemplos.
