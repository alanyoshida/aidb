# Proposal

## Why

Hoje o portal não monitora a disponibilidade das conexões de banco cadastradas por sistema. Falhas de rede, credenciais expiradas ou bancos desligados só são descobertas pelo agente ao tentar usar o MCP server — sem nenhuma sinalização prévia para o editor ou admin. Isso torna operacional o diagnóstico de problemas de conectividade.

## What Changes

- `DbConnection` ganha um campo `status` (`healthy` | `degraded` | `unknown`) e `status_checked_at`.
- O reconciliador do portal (`provisioning.reconcile`) passa a verificar a conectividade de cada conexão dos sistemas ativos, atualizando o status.
- A UI do sistema exibe um badge de saúde em cada card de conexão (verde/amarelo/vermelho).
- O admin pode ver conexões degradadas no painel de administração para diagnóstico rápido.

## Capabilities

### New Capabilities

_(nenhuma — extensão de comportamento existente)_

### Modified Capabilities

- `db-connections`: novos requisitos de monitoramento de saúde e visibilidade do estado da conexão.

## Impact

- **Código**: `portal/appaiforge/models.py` (campos novos em `DbConnection`); migration Alembic; `portal/appaiforge/provisioning.py` (`reconcile`); `portal/appaiforge/services/connections.py` (função de check); `portal/appaiforge/ui/system_detail.py` (badge); `portal/appaiforge/ui/admin.py` (visão de conexões degradadas).
- **Dados**: migration adiciona `status VARCHAR(20) DEFAULT 'unknown'` e `status_checked_at TIMESTAMP` em `db_connections`.
- **Testes**: unit (check de saúde, atualização de status); E2E (badge na UI após check).
- **Risco de performance**: o reconciler verifica conexões com `test_connection()` (5s timeout por conexão). Muitos sistemas com bancos lentos podem tornar o ciclo de reconciliação pesado — mitigado com timeout menor para health check e execução assíncrona por sistema.
