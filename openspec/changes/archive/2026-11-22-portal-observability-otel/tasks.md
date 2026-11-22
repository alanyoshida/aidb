# Tasks

## 1. Dependências

- [x] 1.1 Adicionar ao `portal/pyproject.toml` (com `uv add`, atualizando o `uv.lock`) as dependências `opentelemetry-instrumentation-fastapi`, `-sqlalchemy`, `-httpx`, `-system-metrics` e `opentelemetry-exporter-otlp-proto-http` com o exporter de métricas, todas na série que casa com o SDK 1.45 (0.66b*), conforme design (Risks). Verificar com `uv run python -c` importando os quatro instrumentors e com `uv run pytest -n 8 tests/unit` ainda verde.

## 2. Resource, sampler e sanitização (`telemetry.py`)

- [x] 2.1 Montar o resource com `service.name`, `service.version` (`__version__`) e `service.instance.id` (UUID por processo), mesclado depois com o detector de ambiente, para `OTEL_RESOURCE_ATTRIBUTES` prevalecer (design D5), usado por traços, logs e métricas. Verificar com teste unitário: sem variável, os três atributos estão presentes; com `OTEL_RESOURCE_ATTRIBUTES=deployment.environment=producao,service.version=9.9.9`, o ambiente aparece e a versão é a da variável.
- [x] 2.2 Sampler `ParentBased` que descarta span raiz de kind `CLIENT` (design D2), e `start_run_root_span` com contexto vazio explícito. Verificar com testes unitários:
  - um span `CLIENT` sem pai não é exportado;
  - um span `CLIENT` filho de um span de servidor é exportado;
  - `agent.run` aberto dentro de um span ativo continua raiz, com o trace_id determinístico de `run_trace_id(run_id)`.
- [x] 2.3 Exporter de traços sanitizante em volta do OTLP (design D3): remove `url.query` e tira a query de `url.full`, `http.url` e `http.target`. Verificar com teste unitário: um span com `url.full=https://x/cb?code=abc&state=def` e `url.query=code=abc&state=def` chega ao exporter interno sem `code`, `state` nem `url.query`, e os outros atributos ficam iguais.
- [x] 2.4 `MeterProvider` com leitor periódico e exporter OTLP HTTP só quando `APPAIFORGE_OTEL_METRICS_ENDPOINT` estiver definida (nova configuração `otel_metrics_endpoint` em `config.py`), mais a instrumentação `system-metrics` limitada a `process.*` (design D4). Verificar com testes unitários: sem a variável, nenhum `MeterProvider` com exporter é registrado; com ela, um leitor em memória recebe as métricas de processo.

## 3. Instrumentação do portal e do broker

- [x] 3.1 Configuração da telemetria nativa do FastAPI em `telemetry` (`fastapi_telemetry()`, passada ao `FastAPI()`; ver o achado em design D1), que instrumenta uma app FastAPI com as convenções HTTP estáveis e com `/api/health`, `/health`, `/_nicegui` e o websocket do NiceGUI excluídos (design D1). Chamá-la em `main.create_app()` e na app do broker. Verificar com teste unitário usando `TestClient` e um exporter em memória:
  - uma rota da API gera um span de servidor com método, rota e status;
  - `/api/health` não gera span;
  - uma requisição com `traceparent` continua o traço recebido.
- [x] 3.2 Instrumentar o SQLAlchemy só no engine criado por `db.get_engine()` (design D1), antes do impacto GitNexus em `get_engine`. Verificar com teste unitário: uma consulta pelo engine do portal dentro de um span gera um span filho com o texto parametrizado e sem valores; um engine criado à parte não gera span.
- [x] 3.3 Instrumentar o httpx de forma global. No broker, rodar o encaminhamento com `llm.request` como span corrente (design D6). Verificar com teste unitário no broker, com o upstream simulado:
  - o span httpx da chamada ao LiteLLM é filho de `llm.request`, no trace_id da execução;
  - a requisição de saída leva `traceparent`.
- [x] 3.4 Conferir que o Debug log não mudou: verificar com `uv run pytest -n 8 tests/unit tests/bdd` verde. `test_telemetry.py`, `test_telemetry_logging.py`, `test_telemetry_query.py` e `test_broker.py` incluídos sem alteração de expectativa.

## 4. Collectors, compose e Prometheus

- [x] 4.1 `otel-collector-elastic.yaml`:
  - pipeline de métricas com `cumulativetodelta` até o APM Server (design D4);
  - destino `${env:APM_SERVER_ENDPOINT:-apm-server:8200}` (design D7), confirmando que o Collector 0.112 aceita o default ou subindo a versão.

  Verificar com `docker compose --profile observability-elastic config` sem erro e com o Collector subindo sem erro de configuração no log.
- [x] 4.2 `otel-collector-tempo.yaml` com pipeline de métricas e exporter `prometheus` em `:8889`, e `prometheus.yml` com o job `otel-collector` (design D4). Verificar com os perfis `observability` e `metrics` de pé: o alvo aparece `up` em `/api/v1/targets`, e uma métrica `http_server_request_duration` do portal responde a uma consulta.
- [x] 4.3 Subir `elasticsearch`, `kibana` e `apm-server` do compose para 9.5.6, revendo os argumentos `apm-server.kibana.*` e o heap do ES (design D7). Passar `APPAIFORGE_OTEL_METRICS_ENDPOINT` ao portal e ao broker no compose, como as outras variáveis OTEL. Verificar com o perfil `observability-elastic` de pé, depois de apagar o volume antigo: o ES responde `9.5.6` e o APM Server responde `publish_ready: true`.

## 5. Documentação

- [x] 5.1 ADR 0033 com as decisões D1 a D7: instrumentação programática, sampler, sanitização na origem, temporalidade no Collector, resource, Elastic 9.5.6 com APM Server e o limite das ações da UI. Nota de atualização no ADR 0025 apontando para ela. Verificar que o índice `docs/adr/README.md` lista a ADR nova.
- [x] 5.2 Documentar em `docs/configuracao.md`:
  - `APPAIFORGE_OTEL_TRACES_ENDPOINT`, `_LOGS_ENDPOINT`, `_METRICS_ENDPOINT` e `_SPAN_RETENTION_DAYS`;
  - `OTEL_RESOURCE_ATTRIBUTES`.

  Documentar em `docs/operacao.md`: subir o perfil Elastic, apontar o Collector para um Elastic externo (`APM_SERVER_ENDPOINT` e `--no-deps`) e apagar o volume `elasticsearchdata` ao vir do 8.15. Verificar que os comandos documentados rodam como escritos na verificação do grupo 6.

## 6. Verificação de ponta a ponta

- [x] 6.1 Com o compose e o Collector apontando para o Elastic de teste externo (`APM_SERVER_ENDPOINT=172.30.0.6:8200`):
  - navegar no portal, abrir um chat e rodar uma execução do agente (harness fake) num sistema de teste descartável;
  - verificar no APM do Kibana:
    - `appaiforge-portal` e `appaiforge-broker` aparecem com transações por rota;
    - o traço de uma requisição mostra os spans de banco;
    - o traço da execução mostra `agent.run`, `llm.request` e a chamada ao LiteLLM;
    - não há transações de `/_nicegui` nem de `/api/health`;
    - nenhum documento em `traces-apm*` tem `url.query`;
    - a aba de métricas do serviço tem CPU e memória.
  - Se as páginas do NiceGUI chegarem só como `GET`, aplicar o hook de nome (design, Risks) e repetir.
  - Resultado: tudo conferido, exceto `llm.request` e a chamada ao LiteLLM, que o harness fake não exercita (ele não chama o broker). Esse trecho tem cobertura no teste unitário com servidor HTTP real (3.3). A verificação revelou dois achados, corrigidos e registrados no design D1 e D2: a telemetria nativa do FastAPI duplicava as transações, e os timers do NiceGUI penduravam consultas na transação da página.
- [x] 6.2 Repetir o essencial com o perfil `observability-elastic` local (ES 9.5.6 do compose): um traço do portal e as métricas aparecem no Kibana local. Verificar também que, sem nenhuma variável OTEL, o portal e o broker sobem e atendem sem erros de exportação no log.

## Workflow follow-up

- Arquivar a change (sincronizando `service-observability` e `agent-telemetry`) na mesma branch, antes de abrir a PR. Depois, PR, merge e release.
- Próximas changes: chart com Collector, Secret do Elastic e `kubeletstats`; depois, tracing da borda `/apps/<slug>` pelo Traefik.
