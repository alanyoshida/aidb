# Proposal

## Why

As apps geradas escrevem em **produção** com a credencial da conexão (decisão aceita no MVP, ADR 0015) e o agente tem acesso de leitura/escrita via MCP — hoje **nada impede** um DELETE sem WHERE, um TRUNCATE ou um DROP pedido por engano ao agente ou executado por um bug na app. Este change fecha esse risco com um **gate de operações destrutivas**: DDL é sempre bloqueado; DELETE/UPDATE em massa exigem confirmação explícita — no chat, quando o pedido vem do agente, e como diálogo de confirmação na app gerada, quando vem da interface.

## What Changes

- **Classificador SQL canônico** (sqlglot) em módulo compartilhado: dado um texto SQL, classifica em `normal` (DML escopado, ex.: DELETE por PK), `confirmável` (DELETE/UPDATE sem WHERE restritivo ou com WHERE muito amplo) e `bloqueado` (DDL: DROP/TRUNCATE/ALTER/CREATE... e múltiplas statements com qualquer uma delas). Resistente a comentários, CTEs, case e subqueries.
- **Gate do agente**: opencode configurado com permissionamento para comandos de banco (bash: psql/uv-run-sql) e ferramentas MCP de escrita; pedidos de permissão chegam ao portal como eventos e viram **botões aprovar/recusar no chat**. O portal classifica com o classificador canônico: `bloqueado` é recusado automaticamente (registrado); `confirmável` aguarda decisão do editor (auto-aprovação, com autor, SQL e decisão registrados).
- **Gate da app gerada**: template canônico de camada de acesso a dados (mesmo classificador) que a guidelines torna obrigatório — statements `confirmáveis` disparam diálogo de confirmação na UI com contagem estimada de linhas afetadas; `bloqueadas` são recusadas com mensagem clara.
- **Auditoria**: registro persistente de toda decisão do gate (aprovada, recusada, bloqueada — com autor, SQL, conexão e timestamp), visível na página do sistema.
- Configuração de opencode.json e guidelines atualizadas; nenhuma mudança na estrutura de containers.

**Fora do escopo**: credencial de banco restrita por schema/tabela (change própria); gate em outros bancos além de Postgres (acompanha o multi-banco); bloqueio de custo; desfazer operações aprovadas.

## Capabilities

### New Capabilities

- `destructive-gate`: classificação SQL canônica, gate do agente com aprovação no chat, gate da app gerada com confirmação na UI, e auditoria das decisões.

### Modified Capabilities

(nenhuma — o gate é aditivo; os requisitos existentes de `agent-harness` e `app-serving` permanecem verdadeiros)

## Impact

- **Código**: novo módulo do portal (classificador + serviço de gate/auditoria), evento de permissão no adapter do harness (normalizador e `reply`), UI de aprovação no chat, novo módulo em `app_template/`, guidelines e `AGENTS.md` atualizados, tabela nova de auditoria (Alembic).
- **Dependência nova**: `sqlglot` no portal e nas apps geradas (via template/guidelines).
- **Comportamento observável novo**: runs do agente podem **pausar** aguardando aprovação (novo estado visível na fila); apps geradas passam a exibir diálogos de confirmação para operações em massa.
- **Risco operacional reduzido**: DDL destrutivo em produção passa a ser impossível pela via agente/app; DML em massa passa a exigir decisão explícita registrada.
