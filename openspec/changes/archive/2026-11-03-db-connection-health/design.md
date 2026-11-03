# Design

## Context

Ver `proposal.md — Why`. Estado atual relevante:

- `provisioning.reconcile()` já roda periodicamente e por sistema: verifica se containers existem e os recria se ausentes. É o gancho natural para health checks de conexão.
- `connections.test_connection()` já existe com timeout de 5s via psycopg — pode ser reutilizado para o check periódico, mas 5s é alto para um loop de reconciliação com muitos sistemas.
- `DbConnection` não tem campo de status; o `_to_safe()` hoje retorna apenas metadados estáticos.

## Goals / Non-Goals

**Goals:**
- Estado de saúde por conexão atualizado a cada ciclo de reconciliação.
- Badge na UI refletindo o estado atual (sem polling do browser — basta carregar ao abrir a aba).
- Visão de conexões degradadas no painel admin.

**Non-Goals:**
- Não dispara notificações (email, Slack) em caso de falha — escopo futuro.
- Não bloqueia o agente se a conexão está degradada — o agente descobre ao usar.
- Não implementa histórico de saúde por conexão.

## Decisions

### D1. Health check no reconciliador existente

O `reconcile()` itera sobre sistemas ativos. Adicionamos um passo interno que itera sobre as conexões de cada sistema e chama um `check_connection_health()` com timeout reduzido (2s) em vez dos 5s do `test_connection()`.

**Alternativa**: job separado de health check. Mais flexível (intervalo diferente), mas adiciona complexidade de scheduling desnecessária no MVP.

### D2. Timeout de 2s para health check

O `test_connection()` usa 5s (adequado para cadastro). Para o check periódico, 2s é suficiente para distinguir banco vivo de banco morto sem travar o ciclo de reconciliação.

### D3. Status como string enum no banco

`status VARCHAR(20) DEFAULT 'unknown'` com valores `healthy`, `degraded`, `unknown`. String em vez de enum do banco para evitar migration ao adicionar estados futuros.

### D4. Não propagar status para o agente

O agente continua recebendo a conexão independente do status. Bloquear o MCP de uma conexão degradada causaria comportamento inesperado para o editor sem sinalização clara. O editor vê o badge e decide.

### D5. reconcile() pula `provisioning` além de `archived`

Sistemas em `provisioning` ainda não têm containers prontos e podem não ter conexões configuradas. O health check adiciona `SystemStatus.provisioning` ao bloco de skip, igual ao `archived`. Sistemas em `error` continuam passando pelo check — podem ter conexões válidas mesmo com container com problema.

### D6. BigQuery no health check despachado igual ao `test_connection`

`check_connection_health` despacha para `_test_bigquery` quando `kind == "bigquery"`, respeitando `BIGQUERY_EMULATOR_HOST` se presente. A alternativa (sempre `unknown` para BQ) evitaria custo de query no GCP a cada ciclo, mas tornaria o badge inútil para conexões BigQuery.

## Risks / Trade-offs

- **Reconciliador lento com muitas conexões** → timeout de 2s + execução sequencial por sistema mitiga; sistemas com muitos bancos lentos ainda podem atrasar o ciclo. Mitigação futura: paralelizar checks por sistema com asyncio.
- **Falso positivo de degradação** → rede instável pode marcar como degradado. Aceitável no MVP; futuramente, 2 falhas consecutivas para mudar status.

## Migration Plan

1. Migration Alembic: `ALTER TABLE db_connections ADD COLUMN status VARCHAR(20) DEFAULT 'unknown', ADD COLUMN status_checked_at TIMESTAMP WITH TIME ZONE`.
2. Implementar `check_connection_health(conn_id)` em `connections.py` — testa, atualiza status/timestamp, nunca levanta exceção.
3. Chamar no `reconcile()` após verificar containers.
4. Atualizar `_to_safe()` para incluir `status` e `status_checked_at`.
5. Badge na UI de system_detail.
6. Visão admin de conexões degradadas.
7. Rollback: reverter migration e remover código de check; sistemas continuam funcionando sem campo de status.
