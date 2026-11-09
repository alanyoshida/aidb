# Design

## Context

Hoje, uma execução do agente (`run_id`) é rastreada apenas em memória: `AgentQueue.buffers: dict[str, RunBuffer]` (`portal/appaiforge/agent_queue.py`) cria um buffer em `run_started` e o remove em `run_finished`/`error`/`interrupted`; o Debug log do chat lê desse buffer, sem retenção além da sessão. `AgentQueue.system_state(system_id)` já expõe `{"running": run_id | None, ...}` via consulta ao banco (`portal/appaiforge/agent_queue.py:140-164`).

O sidecar de banco (`base-image/dbproxy/sidecar.py`) é um processo de longa duração por sistema, sem servidor HTTP próprio; a cada statement classificada, `portal_gate.audit_shadow(ctx, sql, enforced)` (`base-image/dbproxy/portal_gate.py`) já faz POST para `/internal/db-gate/audit` no portal (`portal/appaiforge/main.py:69-89`), autenticado por token de serviço, levando `system_id` no payload — mas não `run_id`.

O broker (`portal/appaiforge/broker.py:59`) já resolve `run_id`/`chat_session_id`/`system_id` a partir do token de inferência opaco.

`deploy/docker-compose.yml` hoje só declara `postgres`, `mysql`, `traefik`, `portal`, `litellm`, `broker` — nenhum serviço usa `profiles:`.

`services/audit.py:record()` é o único ponto de escrita de `ManagementAudit`, chamado de 9 arquivos (checkpoints, guidelines, catalog, connections, directory, provider_keys, systems, admin UI, system_detail UI). `gate.py:73` é o único ponto de escrita de `GateDecision`. Ver `proposal.md` para o porquê e `specs/agent-telemetry/spec.md` para os requisitos.

## Goals / Non-Goals

**Goals:**
- Span tree real por `run_id`, não apenas atributos planos correlacionados.
- Zero condicional de telemetria no código do portal/broker — instrumentação sempre presente, inerte sem collector configurado.
- Cobrir as lacunas de log confirmadas no código (login, rede, ciclo de vida de sistema) sem inventar uma segunda fonte de verdade para o que já é auditado.
- Stack de observabilidade completo, mas inteiramente opcional no deploy.

**Non-Goals:**
- Não substitui `GateDecision` nem `ManagementAudit` como fonte de verdade de compliance.
- Não endereça a Etapa 9 (Tetragon/eBPF) do roadmap — fora de escopo.
- Não implementa alerta/dashboards prontos no Grafana além do necessário para visualizar o span tree e os logs descritos aqui.
- Não migra dados históricos de `RunEventRecord` para Tempo.

## Decisions

### Dois emissores de spans, um SDK cada processo
Portal e broker emitem spans de SDKs OTel independentes, em vez de um emissor único centralizado. Alternativa considerada: broker encaminhar seus eventos para o portal emitir todos os spans. Rejeitada porque o broker já resolve `run_id` sozinho a partir do token, e consolidar exigiria uma chamada de rede nova só para telemetria — contrário ao objetivo de não adicionar chamadas de rede novas (ver decisão do `db.query` abaixo). Cada processo usa seu próprio contexto de propagação, correlacionado pelo mesmo `run_id`/`trace_id` compartilhado.

### `run_id` do `db.query` resolvido no portal, sem chamada de rede nova
O sidecar não sabe o `run_id` (não tem esse contexto) e não deve saber — manter o sidecar sem lógica de negócio é intencional (confinamento). O endpoint já existente `/internal/db-gate/audit` resolve o `run_id` no lado do portal, usando `AgentQueue.system_state(system_id)["running"]` no momento em que o audit chega. Alternativa considerada: o sidecar receber o `run_id` do portal e repassá-lo no payload de audit. Rejeitada por exigir um canal novo de portal→sidecar só para isso, quando o portal já pode olhar o estado vivo da fila no momento em que recebe o audit.

### Span `agent.run` mantido em memória, reaproveitando o padrão de `AgentQueue.buffers`
Um dict `trace_contexts: dict[str, Span]` (ou equivalente) vive no processo do portal, criado em `run_started` e encerrado/removido em `run_finished`/`error`/`interrupted` — mesmo ciclo de vida do `AgentQueue.buffers` já existente. Spans filhos (`db.query`, `tool.bash`, `tool.edit`, `policy.decision`) são abertos como filhos do span vivo correspondente ao `run_id` do evento. Alternativa considerada: span "flat" com atributos de correlação em vez de árvore real. Rejeitada por decisão explícita do usuário — quer navegação em árvore no Tempo/Grafana, não apenas busca por atributo.

### Stack completo (Prometheus, Tempo, Loki, Grafana), não uma versão mínima
Decisão explícita do usuário, contra a recomendação inicial de começar só com Tempo+Grafana. Os quatro componentes entram juntos desde o primeiro deploy do profile `observability`.

### Inteiramente opcional via Docker Compose profile
`deploy/docker-compose.yml` ganha um profile `observability` cobrindo Prometheus, Tempo, Loki e Grafana. `portal` e `broker` permanecem fora de qualquer profile (sempre ativos, como hoje) e **sempre instrumentados** — a ausência do profile apenas significa que não há endpoint de exportação configurado, e o SDK OTel já se comporta como no-op nesse caso (não é um `if` no código da aplicação, é o comportamento padrão do SDK sem exporter configurado). Alternativa considerada: flag de ambiente `TELEMETRY_ENABLED` lida pelo código da aplicação. Rejeitada explicitamente pelo usuário — quer zero condicional de telemetria no código.

### Logs novos: só Loki, sem tabela Postgres nova
Para login/tentativas de login e para mudanças de configuração de sistema (rede e ciclo de vida), não existe hoje nenhum registro em Postgres — confirmado por leitura de código (`auth.py`, `services/network_policy.py`, `provisioning.py`, `services/systems.py:set_status`). Como não há nada para espelhar, essas fontes vão direto para Loki, sem nova tabela. Prompts do chat seguem a mesma forma (Loki direto), apesar de já existirem em `AgentRun.prompt`/Postgres — decisão explícita do usuário em nome de observabilidade unificada num único painel, aceitando a redundância.

### Ações administrativas: mantém Postgres como está, adiciona espelho em Loki em um único ponto
Diferente da avaliação inicial (corrigida nesta exploração): `ManagementAudit` não é código morto — é escrita ativa via `services/audit.py:record()`, chamado de 9 arquivos, com UI funcional (`admin.py:_audit_panel()`) e uma spec OpenSpec aprovada (`management-audit`, 4 requisitos). A decisão final é manter esse fluxo inalterado e adicionar a emissão para Loki dentro do próprio `record()` — um único ponto de instrumentação cobre as 9 chamadas existentes, sem tocar em nenhum dos 9 call sites individualmente.

### `GateDecision` não é tocado
Mesma lógica aplicada a `GateDecision` (`gate.py:73`, dado de compliance sem TTL): permanece exatamente como está, sem espelho em Loki e sem substituição por Tempo. Diferente das "ações administrativas", o usuário não pediu espelho aqui — só confirmou que o fluxo de decisão de gate não muda.

### Debug log do chat: única view que passa a refletir o rastreamento
Das views existentes, só o Debug log passa a consultar o span tree (quando o stack está ligado); nenhuma outra tela do portal muda de fonte de dados nesta change.

## Risks / Trade-offs

- [Prompts duplicados em dois sistemas (Postgres e Loki)] → Aceito explicitamente pelo usuário; sem ação de mitigação nesta change.
- [Ausência do profile `observability` deixa o Debug log sem árvore de spans, só com o comportamento atual] → Coberto pelo requisito "Debug log do chat reflete o rastreamento quando disponível" — comportamento atual é o fallback, não uma falha.
- [SDK OTel sem exporter configurado ainda adiciona overhead de criação de spans, mesmo em no-op] → Overhead esperado é mínimo (prática padrão de bibliotecas OTel); não medido nesta change, mas pode ser revisitado se o `audit`/`db.query` no caminho crítico do sidecar mostrar impacto perceptível.
- [Primeiro uso de `profiles:` no compose do projeto] → Manter `portal`/`broker`/`litellm` fora de qualquer profile evita quebrar o fluxo de deploy padrão hoje.

## Migration Plan

1. Adicionar dependências OTel (SDK Python) ao portal e ao broker.
2. Instrumentar `agent_queue.py` com o dict de spans vivos por `run_id` e os pontos de abertura/encerramento já existentes (`run_started`/`run_finished`/`error`/`interrupted`).
3. Instrumentar o endpoint `/internal/db-gate/audit` para anexar o span de `db.query` ao span vivo correspondente, quando houver execução em curso.
4. Instrumentar o broker para emitir `llm.request` usando o `run_id` já resolvido do token.
5. Adicionar logging estruturado em `auth.py`, `services/network_policy.py`, `provisioning.py`/`services/systems.py` (ciclo de vida) e no ponto de envio de prompt do chat.
6. Adicionar a emissão para Loki dentro de `services/audit.py:record()`.
7. Adicionar o profile `observability` ao `deploy/docker-compose.yml` com Prometheus, Tempo, Loki e Grafana.
8. Atualizar o Debug log do chat para consultar Tempo quando o stack estiver disponível, mantendo o fallback atual.

Rollback: remover o profile `observability` do deploy (stack para de rodar; aplicação continua operando normalmente pelo design "sempre instrumentado, no-op sem exporter"). Os logs estruturados novos (login, rede, ciclo de vida, prompts) continuam sendo emitidos mesmo sem o stack, mas não ficam visíveis sem o Loki; isso é aceitável porque nenhuma dessas fontes é hoje consultada por nenhuma tela do portal.
