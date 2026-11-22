# Proposal

## Why

Hoje o portal e o broker só emitem os spans manuais da execução do agente (`agent.run`, `db.query`, `tool.*`, `llm.request`) e alguns logs estruturados. As requisições HTTP, as consultas ao banco do próprio portal e as chamadas de saída não aparecem em lugar nenhum, e não há métricas. Num APM (o alvo é o Elastic APM, ADR 0025), o portal aparece quase vazio: não dá para ver a latência por rota, a taxa de erro, as consultas lentas nem a saúde do processo.

Esta é a primeira de três changes de observabilidade, na ordem portal, depois Kubernetes (chart), depois a borda das apps. Ela vem primeiro porque vale nos dois drivers e porque as outras duas dependem de o portal já falar OTLP completo.

## What Changes

- Auto-instrumentação OpenTelemetry no portal e no broker:
  - requisições FastAPI, com propagação de `traceparent` recebido;
  - consultas SQLAlchemy só do engine do próprio portal;
  - chamadas httpx de saída.
- Ruído e dados sensíveis tratados na origem:
  - caminhos internos (assets e websocket do NiceGUI, health check) fora dos traços;
  - query string removida dos spans HTTP;
  - spans raiz de cliente feitos em segundo plano, sem requisição de origem, descartados.
- Métricas OTLP do portal e do broker (HTTP, pool do banco, processo), ligadas por uma variável nova `APPAIFORGE_OTEL_METRICS_ENDPOINT`. Sem ela, nada muda.
- Identificação do serviço na telemetria:
  - `service.name`, `service.version`, `service.instance.id`;
  - `deployment.environment` pela variável padrão `OTEL_RESOURCE_ATTRIBUTES`.
- A chamada do broker ao LiteLLM aparece no traço da execução, abaixo de `llm.request`.
- Collectors dos dois perfis de exemplo com pipeline de métricas:
  - Elastic: para o APM Server;
  - Grafana: exposto para o Prometheus.
- No perfil `observability-elastic` do compose:
  - Elasticsearch, Kibana e APM Server sobem de 8.15.3 para 9.5.6, a versão do ambiente de teste externo;
  - o destino do APM Server passa a ser configurável, para o mesmo Collector mandar para um Elastic externo.
- **BREAKING** (só para quem já usava o perfil `observability-elastic`): o volume `elasticsearchdata` criado pelo 8.15.3 não sobe no 9.5.6 e precisa ser apagado. São dados de exemplo.

## Capabilities

### New Capabilities

- `service-observability`: o que portal e broker expõem a um APM:
  - traços automáticos de requisições, banco e chamadas de saída;
  - métricas;
  - identificação do serviço;
  - o que fica fora da telemetria (ruído e dados sensíveis).

  As changes seguintes (chart e borda das apps) estendem esta capability.

### Modified Capabilities

- `agent-telemetry`:
  - a exportação agnóstica de backend passa a cobrir métricas, além de traços e logs;
  - o traço da execução passa a incluir a chamada do broker ao provedor de LLM.

## Impact

- **Código:**
  - `portal/appaiforge/telemetry.py`: resource, métricas, instrumentações, sampler, sanitização;
  - `main.py` e `broker_app.py`: instrumentar as apps FastAPI e o engine;
  - `config.py`: nova variável de métricas.
- **Dependências:** `opentelemetry-instrumentation-fastapi`, `-sqlalchemy`, `-httpx` e `-system-metrics`, na série que casa com o SDK 1.45 (0.66b*).
- **Deploy:**
  - `deploy/docker-compose.yml`: versões Elastic, variáveis OTEL de portal e broker;
  - `deploy/observability/otel-collector-elastic.yaml`, `otel-collector-tempo.yaml` e `prometheus.yml`.
- **Docs:** nova ADR 0033, `docs/configuracao.md` e `docs/operacao.md` (como apontar para um Elastic externo, migração do volume).
- **Fora do escopo:**
  - chart Helm e Kubernetes (próxima change);
  - tracing do Traefik e da borda `/apps/<slug>` (change seguinte);
  - instrumentação dentro das apps geradas;
  - ligar o security do Elastic.
