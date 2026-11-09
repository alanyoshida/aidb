# Design

## Context

Ver proposal.md - Why. Hoje `telemetry.py` já usa o SDK OTel puro (OTLP), mas o endpoint de exportação aponta direto para um backend específico (Tempo/Loki), e `telemetry_query.py` consulta a API REST proprietária do Tempo para alimentar o Debug log do chat.

Pontos relevantes já existentes no projeto, usados como base para as decisões abaixo:
- Portal e broker já compartilham a mesma Postgres (`session_scope()`), usada hoje por `gate.py`, `AgentQueue` e `audit.py`.
- O projeto usa Alembic para migrações (`portal/alembic.ini`, `portal/migrations/`).
- `RunEventRecord` (tabela `run_events`) é o precedente mais próximo de uma tabela de eventos por `run_id`, com FK para `agent_runs.id`.
- `reconcile_orphaned_runs()` já roda uma vez no startup do portal (`create_app`, `main.py`) — não existe hoje nenhum job periódico recorrente dentro do processo do portal.
- NiceGUI já é usado para timers de UI por página (`ui.timer`, em `chat.py`, `system_detail.py`, `admin.py`); o equivalente a nível de aplicação (`app.timer`, independente de qualquer página aberta) ainda não é usado no projeto.
- O padrão "no-op por padrão, best-effort quando configurado" já estabelecido em `telemetry.py`/`telemetry_query.py` (ex.: `fetch_run_trace` devolve `None` em qualquer falha, sem propagar erro) é reaproveitado aqui.

## Goals / Non-Goals

**Goals:**
- O endpoint de exportação configurado na aplicação nunca nomeia um backend específico — ele sempre aponta para um OTel Collector, cuja configuração própria decide o destino final.
- O Debug log do chat lê exclusivamente de uma tabela própria em Postgres, sem depender da API de nenhum backend de observabilidade externo.
- A troca de backend de observabilidade (Tempo/Loki/Grafana ↔ Elasticsearch/Kibana/APM) é demonstrada de forma concreta com dois profiles de exemplo no docker-compose, sem nenhuma mudança de código.
- A nova tabela de spans tem uma política de retenção (TTL) desde o início.

**Non-Goals:**
- Não altera `GateDecision` nem `ManagementAudit` (ver spec `agent-telemetry` - "Não substituição dos registros de auditoria e de gate existentes").
- Não cria um painel administrativo para escolher/configurar o backend de observabilidade — a escolha continua sendo feita na configuração de deploy (docker-compose/env vars), como hoje.
- Não busca paridade com funcionalidades nativas do Kibana APM (service maps, detecção de anomalia) — o profile `observability-elastic` prova que a ingestão OTLP funciona, não que a experiência do Kibana fica tão rica quanto com os agentes nativos da Elastic.
- Não introduz retenção para `AgentRun`/`RunEventRecord` — eles continuam sem limpeza automática, como hoje; a retenção desta change é escopada estritamente à nova tabela de spans.
- Não adiciona pipeline de métricas (Prometheus já existe no profile atual e permanece sem mudanças).

## Decisions

### 1. Exportação sempre via OTel Collector, nunca direto a um backend
O endpoint de exportação (`APPAIFORGE_OTEL_TRACES_ENDPOINT`/`APPAIFORGE_OTEL_LOGS_ENDPOINT`) passa a apontar, em qualquer ambiente com observabilidade habilitada, para um Collector cujo endereço não muda entre backends. A troca de backend é só uma troca do bloco `exporters:` na configuração do Collector (mesmo binário, config diferente), nunca da aplicação.

Nenhuma mudança de código é necessária em `telemetry.py` para isso — os dois endpoints já são URLs configuráveis livremente por env var; a mudança é inteiramente de infraestrutura (novo serviço Collector no docker-compose, e os dois profiles de backend passam a exportar através dele).

Alternativa considerada: manter o endpoint apontando direto pro backend (como hoje) e só documentar "troque a URL pro backend que preferir". Funcionaria tecnicamente (OTLP já é aceito nativamente por Tempo, Loki e Elastic APM Server), mas deixaria a app "sabendo" implicitamente que existe um backend específico por trás de cada URL, e tornaria o fan-out (exportar pra dois backends ao mesmo tempo, útil em migração) impossível sem duplicar exporters na própria aplicação.

### 2. Debug log lido de uma tabela Postgres, populada por um `SpanProcessor` próprio
Mantém um único ponto de criação de span (`telemetry.start_run_root_span`/`start_child_span`, sem mudança de assinatura). Um `SpanProcessor` customizado é registrado no mesmo `TracerProvider` ao lado do `BatchSpanProcessor` existente; no `on_end()` de qualquer span, ele persiste a linha correspondente numa tabela nova (`agent_telemetry_spans`, por analogia a `run_events`: FK pra `agent_runs.id`, índice por `run_id`). A escrita em Postgres é best-effort (nunca propaga exceção pro código de negócio) e deve ser enfileirada/batcheada pelo próprio processor, para não bloquear o caminho de execução no `on_end()` síncrono.

`telemetry_query.fetch_run_trace(run_id)` é reescrito para consultar essa tabela em vez da API REST do Tempo, mantendo a mesma assinatura e o mesmo formato de retorno (lista de spans ordenada, com `parent_span_id`/`attributes`) — `chat.py` não muda no ponto de chamada.

Alternativas consideradas: dual-write explícito em cada call site de instrumentação (rejeitado - duplica código em todo ponto de instrumentação existente e futuro); Postgres como fonte única com exportação derivada por job separado (rejeitado - adiciona uma pipeline de exportação com lag/batching sem ganho claro, já que o `BatchSpanProcessor` de exportação já resolve isso de forma independente).

### 3. Retenção por TTL via job periódico no próprio processo do portal
Um `app.timer` (nível de aplicação, não de página) registrado uma vez no startup do portal — ao lado de `reconcile_orphaned_runs()`, em `create_app()` — remove periodicamente spans mais antigos que `APPAIFORGE_OTEL_SPAN_RETENTION_DAYS` (default: 30 dias). Não é adicionado nenhum componente de infraestrutura novo (sem cron container, sem APScheduler) - reaproveita o mesmo mecanismo de timer que o NiceGUI já usa em todo o resto da UI, só que a nível de app em vez de por página.

Alternativa considerada: cron externo (container dedicado ou cron do SO) chamando um script de limpeza. Mais desacoplado do ciclo de vida do processo, mas introduz um componente novo que o projeto não tem hoje, pra um job simples o suficiente pra caber num timer de app.

### 4. Dois profiles de exemplo no docker-compose, alimentados pelo mesmo Collector
`observability` (existente: Tempo, Loki, Grafana) ganha o Collector na frente. `observability-elastic` (novo: Elasticsearch, Kibana, APM Server ou Elastic Agent) é adicionado como segundo exemplo completo, usando o mesmo Collector com um arquivo de config de exporters diferente. Nenhum dos dois profiles é ligado por padrão (mesma disciplina do profile `observability` atual).

## Risks / Trade-offs

- [Risco] Collector mal configurado descarta telemetria silenciosamente, sem erro visível na aplicação → Mitigação: os dois profiles de exemplo já vêm com a config do Collector testada; o único invariante que a aplicação precisa conhecer é o endpoint fixo do Collector.
- [Risco] Escrita em Postgres no `on_end()` de cada span pode adicionar latência ao caminho de execução se feita de forma síncrona → Mitigação: processor próprio deve batchear/enfileirar como o `BatchSpanProcessor` já faz, e falhar silenciosamente (best-effort), nunca bloqueando ou lançando erro.
- [Risco] Política de retenção é nova para o projeto (nenhuma outra tabela tem limpeza automática hoje) → Mitigação: escopo estritamente limitado à nova tabela de spans; `AgentRun`/`RunEventRecord` permanecem como estão, fora do escopo desta change.
- [Risco] Manter dois profiles de exemplo (Tempo e Elastic) dobra a superfície de infraestrutura testada → Mitigação: decisão já tomada e aceita; o profile Elastic é um exemplo de referência, não um caminho de produção continuamente monitorado pelo projeto.
- [Risco] Elasticsearch em modo dev tem footprint de memória pesado no ambiente compartilhado → Mitigação: `observability-elastic` continua opt-in, nunca ligado por padrão, mesma disciplina do profile `observability` já existente.

## Migration Plan

1. Nova migração Alembic cria `agent_telemetry_spans` (FK `agent_runs.id`, índice por `run_id`), sem afetar tabelas existentes.
2. `telemetry.py` ganha o `SpanProcessor` novo registrado ao lado do `BatchSpanProcessor` existente - puramente aditivo, nenhuma mudança de comportamento na exportação já existente.
3. `telemetry_query.py` é reescrito para consultar a nova tabela; `chat.py` não muda no ponto de chamada (mesma assinatura).
4. `docker-compose.yml`: profile `observability` ganha o serviço Collector na frente de Tempo/Loki/Grafana; novo profile `observability-elastic` é adicionado.
5. Rollout: a nova tabela e o `SpanProcessor` podem ser implantados antes de qualquer mudança nos valores de `APPAIFORGE_OTEL_TRACES_ENDPOINT`/`APPAIFORGE_OTEL_LOGS_ENDPOINT` (que continuam funcionando como hoje, no-op sem valor, ou apontando direto pro Tempo se já estiverem configurados assim). Só depois os operadores apontam esses valores para o Collector.
6. Rollback: caso o Collector apresente problema, os endpoints podem voltar a apontar direto pro backend (Tempo/Loki), já que ele também aceita OTLP nativamente - sem precisar reverter nenhum código.
