# Proposal

## Why

O portal e o broker hoje só expõem execução do agente através do Debug log do chat (eventos em memória, sem retenção) e da tabela `GateDecision` (decisões de SQL destrutivo). Não há como correlacionar, de ponta a ponta, um `run_id` com as queries que ele disparou no banco, as chamadas de LLM, as decisões do gate e as ações de ferramenta — e não há nenhum log centralizado para tentativas de login, mudanças de configuração de rede/ciclo de vida de sistema, nem para os prompts enviados no chat. A Etapa 6 do roadmap de confinamento (`docs/roadmap-confinamento-do-agente.md`) pede telemetria via OpenTelemetry; esta change formaliza o desenho já validado com o usuário: um span tree real por `run_id`, um stack de observabilidade completo (Prometheus, Tempo, Loki, Grafana) opcional no deploy, e logs estruturados para as lacunas de auditoria confirmadas no código.

## What Changes

- Instrumentação OTel sempre ativa no portal e no broker (dois emissores de spans, um SDK cada; sem `if telemetry_enabled` em lugar nenhum — o SDK vira no-op quando não há collector configurado).
- Span `agent.run` mantido em memória por `run_id` (mesmo padrão de ciclo de vida do `AgentQueue.buffers`: criado em `run_started`, encerrado em `run_finished`/`error`/`interrupted`); spans filhos (`db.query`, `tool.bash`, `tool.edit`, `policy.decision`) anexados a esse contexto vivo conforme os eventos chegam.
- `db.query` resolve o `run_id` no endpoint existente `/internal/db-gate/audit` (portal), via `AgentQueue.system_state(system_id)["running"]` — sem nova chamada de rede entre sidecar e portal.
- `llm.request` emitido pelo broker, que já resolve `run_id`/`chat_session_id`/`system_id` a partir do token de inferência.
- Novo stack de observabilidade opcional via Docker Compose profile `observability` (Prometheus, Tempo, Loki, Grafana) — ausente por padrão; `deploy/docker-compose.yml` não usa `profiles:` hoje, este é o primeiro uso.
- Debug log do chat passa a ler de Tempo (span tree do `run_id`/`chat_session_id`) em vez de só do buffer em memória, quando o stack de observabilidade está ligado; sem o stack, continua como está hoje (sem regressão).
- Logs estruturados (Loki) para fontes hoje sem nenhum registro:
  - Tentativas de login (sucesso e falha) — `auth.py` não grava nenhuma hoje.
  - Mudanças de configuração de rede: `set_internet_enabled`, `set_restricted_network`, `add_allowed_domain`, `remove_allowed_domain` (`services/network_policy.py`) — zero rastro hoje.
  - Ciclo de vida de sistema: `archive_system`, `delete_system`, `set_status` (`provisioning.py`, `services/systems.py`) — zero rastro hoje.
  - Prompts enviados no chat — redundante com `AgentRun.prompt` (Postgres), mantido por decisão do usuário para observabilidade unificada num único painel.
  - Checkpoints: já cobertos por `audit.record()`; sem mudança.
- `services/audit.py:record()` ganha um espelho para Loki em cada chamada (ponto único, cobre as 9 chamadas existentes de "ações administrativas" — usuários/grupos, revogar inferência, chaves de provedor, conexões, catálogo). `ManagementAudit`/Postgres continua exatamente como está, sem remoção.
- `GateDecision`/Postgres continua exatamente como está (dado de compliance, sem TTL) — não é substituído por Tempo/Loki.

## Capabilities

### New Capabilities
- `agent-telemetry`: traços OTel (span tree por `run_id` cobrindo `db.query`, `tool.*`, `policy.decision`, `llm.request`), stack de observabilidade opcional no deploy, e logs estruturados centralizados para login/tentativas de login, mudanças de configuração de sistema (rede e ciclo de vida) e prompts do chat, incluindo o espelho em log das ações administrativas já auditadas em Postgres.

### Modified Capabilities
(nenhuma — `management-audit` e o fluxo de `GateDecision` permanecem com o mesmo comportamento e requisitos; esta change só adiciona observabilidade ao lado deles.)

## Impact

- **Portal** (`portal/appaiforge/`): `agent_queue.py` (contexto de span por `run_id`), `main.py` (endpoint `/internal/db-gate/audit`), `auth.py`, `services/network_policy.py`, `services/systems.py`, `provisioning.py`, `services/audit.py`, `ui/chat.py` (Debug log).
- **Broker**: emissão de `llm.request`.
- **Deploy**: `deploy/docker-compose.yml` (novo profile `observability` com Prometheus, Tempo, Loki, Grafana).
- **Dependências novas**: SDKs OTel para Python (portal e broker), coletor/stack de observabilidade (imagens Docker).
- Nenhuma mudança de requisito em `management-audit` ou no fluxo de `GateDecision` — ambos continuam como hoje.
