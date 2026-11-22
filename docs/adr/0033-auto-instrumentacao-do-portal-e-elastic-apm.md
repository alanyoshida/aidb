# 0033 — Auto-instrumentação OTel do portal e do broker, com o Elastic APM como destino de referência

* Status: aceito
* Data: 2026-11-22
* Decidida em: change `portal-observability-otel` (primeira de três: portal, depois chart Kubernetes,
  depois a borda das apps)
* Relacionada: [ADR 0025](0025-telemetria-otel-agnostica-de-backend.md) (Collector como endpoint
  fixo, que esta ADR mantém); [ADR 0026](0026-metricas-de-recursos-por-container-via-cadvisor.md)
  (métricas de recursos dos sistemas, que continuam com o cAdvisor)

## Contexto

O portal e o broker só emitiam os spans manuais da execução do agente e alguns logs. Num APM, o
portal aparecia quase vazio: sem requisições HTTP, sem consultas ao banco, sem chamadas de saída e
sem métricas. O destino de referência escolhido pelo operador é um Elastic próprio (Elasticsearch,
Kibana e APM Server 9.5.6, sem Fleet), mas o ADR 0025 exige que nada do Elastic entre na aplicação.

## Decisão

**Instrumentação programática dentro de `telemetry`, e não `opentelemetry-instrument`.** httpx e
métricas de processo são ligados por código, sobre o `TracerProvider` que já existe (gerador de IDs
determinístico do `agent.run` e exporter Postgres do Debug log). O wrapper de linha de comando criaria
outro provider e mudaria o entrypoint do compose e do chart.

**Requisições pela telemetria nativa do FastAPI.** O FastAPI 0.162 já traz telemetria OpenTelemetry
ligada por padrão; somar o `FastAPIInstrumentor` do contrib duplicava cada transação, e a do contrib
saía sem nome nas páginas do NiceGUI. Portal e broker passam `telemetry=fastapi_telemetry()` ao
`FastAPI()`: exclusão de health, assets e websocket do NiceGUI; `operation_spans` desligado (ruído);
`logs` desligado (as falhas de validação levariam os valores de entrada).

**SQLAlchemy só no engine do portal, pelo `EngineTracer`.** `SQLAlchemyInstrumentor().instrument()`
envolve o `create_engine` global mesmo quando recebe um engine, e passaria a instrumentar qualquer
engine futuro de conexão de usuário, cujo SQL gerado pelo agente pode trazer literais com dados
pessoais. O `EngineTracer` registra listeners só no engine dado, chamado em `main.create_app()`.

**Span raiz de cliente é descartado no sampler.** `ParentBased`, com a regra para raízes: `CLIENT`
sem pai não é amostrado. Corta as consultas e chamadas httpx de trabalho em segundo plano
(reconciliação, timers, handlers do websocket da UI), que virariam traços de um span só. O
`agent.run` (`INTERNAL`) e os spans de servidor continuam. Um span cujo pai local já terminou também não é
amostrado: os timers do NiceGUI copiam o contexto da requisição da página e penduravam consultas
periódicas na transação dela, muito depois de ela terminar. `agent.run` abre com contexto vazio
explícito, para não herdar um span corrente e perder o trace_id determinístico.

**Query string removida na origem.** Um exporter envolve o OTLP e remove `url.query` e a query de
`url.full`/`http.url`/`http.target` antes de o span sair do processo — o `code` do retorno OIDC
nunca chega ao Collector. Cabeçalhos e corpos não são capturados.

**Métricas cumulativas no SDK, delta no Collector do Elastic.** O SDK fica no padrão (o que o
Prometheus espera), e o pipeline de métricas do Collector do perfil Elastic usa `cumulativetodelta`
antes do APM Server. A particularidade do backend fica no Collector, como pede o ADR 0025.

**Resource com padrões no código e ambiente do operador.** `service.name`, `service.version`
(`__version__`) e `service.instance.id` vêm do código; `OTEL_RESOURCE_ATTRIBUTES` prevalece (ex.:
`deployment.environment`, `service.version`).

**APM Server standalone como caminho para um Elastic próprio.** Sem Fleet (que exige o security do
Elastic ligado), o APM Server standalone, na mesma versão do Elasticsearch, recebe OTLP na porta 8200
e grava nos templates que o Elasticsearch 9 já instala. O compose de exemplo sobe para 9.5.6, e o
Collector aceita um APM Server externo por `APM_SERVER_ENDPOINT`.

## Alternativas consideradas

- **`opentelemetry-instrument` no comando de subida** — descartada: segundo `TracerProvider` em
  conflito com o atual, entrypoint diferente por deploy e SQLAlchemy global.
- **Filtrar ruído e query string só no Collector** — descartada: o lixo e o `code` do OIDC já teriam
  saído do processo. O Collector pode repetir a sanitização como defesa extra na change da borda.
- **Temporalidade delta no SDK** — descartada: quebraria o perfil Grafana/Prometheus, e uma
  variável de temporalidade por backend na aplicação viola o ADR 0025.
- **EDOT Collector gravando direto no Elasticsearch** — descartada para este caminho: exige trocar o
  Collector contrib pela distribuição da Elastic; o APM Server standalone mantém o mesmo Collector
  do compose.

## Consequências

- As ações da UI chegam pelo websocket do NiceGUI e não geram span de servidor; suas consultas são
  descartadas pelo sampler. Ficam invisíveis no APM até alguém instrumentar os eventos do NiceGUI.
- `service.version` só faz sentido quando o operador o define: `__version__` está parado em `0.1.0`.
  A change do chart deve preencher com a tag da imagem.
- O volume `elasticsearchdata` do compose criado pelo 8.15.3 não abre no 9.5.6 e precisa ser apagado
  (dados de exemplo).
- O span `llm.request` termina quando a resposta do LiteLLM começa, não ao fim do streaming; a
  chamada httpx filha dele herda esse limite.
