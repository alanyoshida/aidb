# Tasks

## 1. Tabela de spans em Postgres

- [x] 1.1 Adicionar o modelo `AgentTelemetrySpan` (tabela `agent_telemetry_spans`) em `models.py`: `id`, `run_id` (FK `agent_runs.id`, indexado), `span_id`, `parent_span_id` (nullable), `name`, `start_time`, `end_time`, `attributes` (JSON); criar a migração Alembic correspondente; verificar que `alembic upgrade head` e `alembic downgrade -1` rodam sem erro. (confirmado: migração `7980e9fe94fe` aplicada e revertida com sucesso contra o Postgres real do ambiente dev, via `docker compose exec portal alembic upgrade head`/`downgrade -1`)

## 2. `SpanProcessor` de persistência

- [x] 2.1 Implementar um `SpanProcessor` customizado em `telemetry.py` que, no `on_end()`, grava a linha correspondente em Postgres de forma best-effort (nunca propaga exceção) e sem bloquear o chamador síncrono; registrar esse processor no mesmo `TracerProvider` que já tem o `BatchSpanProcessor` de exportação, sempre ativo, independente de qualquer endpoint de exportação estar configurado; verificar com teste unitário que um span criado via `start_run_root_span`/`start_child_span` aparece na tabela depois de `.end()`, mesmo sem nenhum endpoint de exportação definido. (implementado como `_PostgresSpanExporter` dentro de um `BatchSpanProcessor` próprio — reaproveita a fila/thread de background já comprovada do SDK em vez de um processor artesanal; `configure()` agora sempre cria o `TracerProvider`, independente de endpoint de exportação; `test_spans_de_uma_run_real_sao_persistidos_em_postgres_e_lidos_pelo_debug_log` passando)
- [x] 2.2 Verificar com teste que uma falha ao gravar em Postgres (ex.: sessão indisponível) não propaga exceção para o código que criou ou encerrou o span. (`test_postgres_span_exporter_falha_ao_gravar_nao_propaga_e_devolve_failure`; achado ao vivo durante a implementação: um span órfão de outro teste no mesmo lote do `BatchSpanProcessor` derrubava o commit inteiro via `add_all` — corrigido para persistir cada span na sua própria transação, isolando falhas por span)

## 3. Debug log lendo de Postgres

- [x] 3.1 Reescrever `telemetry_query.fetch_run_trace(run_id)` para consultar `agent_telemetry_spans` em vez da API REST do Tempo, mantendo a mesma assinatura e o mesmo formato de retorno (lista ordenada de spans com `parent_span_id`/`attributes`); verificar com teste que uma run com spans persistidos devolve a árvore esperada. (`test_consulta_retorna_arvore_ordenada`)
- [x] 3.2 Verificar com teste que uma run sem nenhum span persistido devolve `None` (mesmo contrato de hoje), levando o Debug log a cair no comportamento baseado em eventos em memória sem regressão. (`test_sem_spans_persistidos_devolve_none`)
- [x] 3.3 Remover de `telemetry_query.py` o código de consulta à API do Tempo que não for mais usado, e substituir em `test_telemetry_query.py` os testes que hoje mockam essa API pelos testes equivalentes contra a tabela Postgres. (`httpx`/parsing OTLP-JSON removidos de `telemetry_query.py`; `APPAIFORGE_OTEL_TRACES_QUERY_URL` também removida de `config.py`/`docker-compose.yml`, já que não tinha mais nenhum uso)
- [x] 3.4 Verificar manualmente, com um sistema de teste descartável, que o Debug log de uma sessão com execução recente exibe a árvore de spans corretamente lendo de Postgres, sem nenhum endpoint de exportação de observabilidade configurado. (confirmado ao vivo no sistema de teste "Collector Verify": `agent.run (11883ms)` + `tool.bash (150ms)` com atributos, lido via `telemetry_query.fetch_run_trace` → Postgres)

## 4. Retenção por TTL

- [x] 4.1 Adicionar `APPAIFORGE_OTEL_SPAN_RETENTION_DAYS` (default 30) em `config.py`; implementar a função de limpeza que remove spans com `end_time` além da retenção configurada; verificar com teste que spans antigos são removidos e spans recentes são preservados. (`telemetry.cleanup_expired_spans`; `test_cleanup_expired_spans_remove_antigos_e_preserva_recentes`)
- [x] 4.2 Registrar essa limpeza como `app.timer` recorrente no startup do portal (`create_app`, ao lado de `reconcile_orphaned_runs()`); verificar que o timer é registrado uma única vez e que o intervalo de execução é razoável (ex.: a cada algumas horas, não a cada poucos segundos). (`telemetry.start_span_cleanup_timer()`, chamada por `create_app()`; extraído pra `telemetry.py` em vez de ficar inline em `main.py` pra ser testável sem disparar os efeitos colaterais pesados de importar `main.py` — `test_start_span_cleanup_timer_usa_intervalo_de_horas_nao_segundos`)

## 5. Collector agnóstico de backend

- [x] 5.1 Adicionar o serviço do OTel Collector ao profile `observability` existente no `docker-compose.yml`, com um arquivo de config em `deploy/observability/` cujos exporters apontam pro Tempo/Loki já existentes; portal e broker passam a apontar `APPAIFORGE_OTEL_TRACES_ENDPOINT`/`APPAIFORGE_OTEL_LOGS_ENDPOINT` pro Collector em vez de direto pro Tempo/Loki; verificar que `docker compose --profile observability up -d` sobe o Collector e que um span de uma execução real ainda aparece no Tempo via Grafana, agora passando pelo Collector. (confirmado ao vivo: `otel-collector-tempo` recebeu OTLP do portal e repassou pro Tempo — `agent.run (11883ms)` encontrado via `/api/search` do Tempo com o mesmo `run_id` do Debug log)
- [x] 5.2 Verificar que o deploy sem o profile `observability` continua funcionando normalmente (Collector nunca sobe por padrão), confirmando que a mudança não introduz nenhuma dependência nova obrigatória. (`docker compose config --services` sem profile não lista `otel-collector-tempo`/`otel-collector-elastic`/nenhum serviço de observabilidade; portal/broker reais permaneceram saudáveis durante toda a verificação)

## 6. Profile de exemplo Elastic

- [x] 6.1 Adicionar um novo profile `observability-elastic` ao `docker-compose.yml` com Elasticsearch, Kibana e APM Server (ou Elastic Agent) configurados para receber OTLP, junto com um segundo arquivo de config do Collector cujos exporters apontam pra esse stack; verificar que `docker compose --profile observability-elastic up -d` sobe os 3 serviços e que todos ficam saudáveis. (confirmado: `elasticsearch`/`kibana`/`apm-server`/`otel-collector-elastic` subiram e ficaram saudáveis; `curl localhost:9200/_cluster/health` → `"status":"green"`)
- [x] 6.2 Verificar ao vivo, com um sistema de teste descartável, que apontar o Collector pro profile `observability-elastic` em vez do `observability` faz um span de execução real aparecer no Kibana, sem nenhuma mudança no código do portal/broker nem no valor de `APPAIFORGE_OTEL_TRACES_ENDPOINT`/`APPAIFORGE_OTEL_LOGS_ENDPOINT` — só a config do Collector e qual profile está de pé mudam. (confirmado ao vivo: mesmo sistema "Collector Verify", mesmos env vars do portal/broker; parei `otel-collector-tempo` e subi `otel-collector-elastic` no alias de rede `otel-collector`; nova execução → `agent.run`/`tool.bash` com o `run_id` certo indexados em `.ds-traces-apm-default-*` do Elasticsearch, e o serviço `appaiforge-portal` visível na UI do Kibana em Observability → APM → Services)

## 7. Verificação de não regressão

- [x] 7.1 Rodar o conjunto completo de testes unitários (`uv run pytest tests/unit`) e confirmar que a troca de `telemetry_query.py` e a adição do novo `SpanProcessor` não quebram nenhum teste existente da change anterior (`test_telemetry.py`, `test_gate.py`, `test_gate_queue.py`). (340 passed, 0 failed)
- [x] 7.2 Verificar manualmente que `GateDecision` e `ManagementAudit` continuam funcionando exatamente como antes (aba "Auditoria de Gestão" do admin, decisões do gate), sem nenhuma chamada nova de telemetria alterando esse comportamento. (confirmado ao vivo: aba "Auditoria" do sistema de teste mostrou "Gate de destrutivas" e "Ações de gestão" normalmente, com `system.create`/`checkpoint.create` registrados)

## Workflow follow-up

- Arquivar esta change (`openspec archive agent-telemetry-backend-agnostic`) depois que as tarefas acima estiverem implementadas e verificadas, seguindo o protocolo de segurança do projeto (nunca em `homolog-crm`, `pets`, `projetos` ou `chat-a0a915bd`; usar sempre um sistema de teste descartável).
- Depois do arquivamento, confirmar que as mudanças de requisito da capability `agent-telemetry` aparecem corretamente em `openspec show agent-telemetry --type spec`.
