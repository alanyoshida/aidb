# Design

## Context

- **`telemetry.configure(service_name)`**, chamada por `main.create_app()` e pelo módulo do broker:
  - monta um `TracerProvider` com o gerador de IDs determinístico do `agent.run` e o `_PostgresSpanExporter`. Este só persiste spans que têm `run_id`, para o Debug log;
  - adiciona o OTLP só se houver `APPAIFORGE_OTEL_TRACES_ENDPOINT`;
  - o resource tem só `service.name`;
  - não existe `MeterProvider`.
- **O portal é FastAPI com o NiceGUI montado** (`ui.run_with(application)`). Por isso o mesmo processo serve:
  - rotas de API;
  - páginas;
  - assets (`/_nicegui/...`);
  - o websocket da UI.

  As ações da UI chegam pelo websocket, não como requisições HTTP.
- **O span raiz `agent.run` nasce numa `threading.Thread`** (`agent_queue._work`). No Python 3.13 sem free-threading, a thread nova não herda o contexto, então o span sai como raiz. É disso que o ID determinístico depende.
- **`db.get_engine()` é o único `create_engine` do portal.** As conexões de usuário usam drivers próprios (psycopg, pymysql, BigQuery), fora do SQLAlchemy.
- **`__version__` está fixo em `0.1.0`**, enquanto as releases já estão na v1.7.0.
- **Collectors do compose:** o perfil Elastic repassa OTLP ao APM Server 8.15.3, e o perfil Grafana repassa ao Tempo e ao Loki. Nenhum dos dois tem pipeline de métricas. O Prometheus está no perfil `metrics` e só raspa o cAdvisor.
- **Ambiente de teste externo:** ES e APM Server 9.5.6 em `172.30.0.6`, sem security. Um traço OTLP de teste já apareceu no APM do Kibana com `agentName: opentelemetry/python`.

## Goals / Non-Goals

**Goals:**
- portal e broker legíveis no APM: transações por rota, banco e saídas no traço, métricas do processo;
- nenhum segredo ou dado de query string saindo do processo;
- o ADR 0025 continua valendo: nenhuma particularidade do Elastic no código.

**Non-Goals:**
- chart, Kubernetes e `kubeletstats` (próxima change);
- tracing do Traefik;
- traços das ações da UI pelo websocket;
- logs de acesso HTTP;
- mudar o Debug log.

## Decisions

### D1. Instrumentação programática dentro de `telemetry`, e não `opentelemetry-instrument`

Achado na verificação ao vivo: o FastAPI 0.162 já traz telemetria OpenTelemetry nativa, ligada por padrão e usando o provider global. Com o `FastAPIInstrumentor` do contrib, cada requisição virava duas transações, e a do contrib saía sem nome nas páginas do NiceGUI e com host errado. A instrumentação de requisições passou a ser a nativa, configurada por `fastapi_telemetry()`:
- exclusão por função sobre o escopo ASGI; ela também cala o app do NiceGUI montado por dentro;
- `operation_spans` desligado, porque spans de dependência e serialização só fazem ruído;
- `logs` desligado, porque as falhas de validação levariam os valores de entrada.

O piso do FastAPI no `pyproject` sobe para 0.162, e a dependência `opentelemetry-instrumentation-fastapi` sai.

As instrumentações FastAPI, SQLAlchemy, httpx e system-metrics são ligadas por código, a partir do módulo `telemetry`:
- a telemetria nativa do FastAPI (`FastAPI(telemetry=telemetry.fastapi_telemetry())`) na app do portal e na do broker;
- SQLAlchemy só no engine de `get_engine()`;
- httpx de forma global.

O wrapper `opentelemetry-instrument` no comando de subida foi descartado por três motivos:
- criaria outro `TracerProvider` e brigaria com o gerador de IDs e o exporter Postgres que já existem;
- mudaria o entrypoint do compose e, depois, o do chart;
- instrumentaria o SQLAlchemy de forma global. Isso pegaria qualquer engine futuro de conexão de usuário, cujo SQL gerado pelo agente pode trazer literais com dados pessoais.

Instrumentar o engine do portal explicitamente cumpre o requisito "conexões de usuário fora" por construção, e não por convenção.

Achado na implementação: `SQLAlchemyInstrumentor().instrument(engine=...)` envolve o `create_engine` global mesmo recebendo um engine. Por isso o engine do portal é instrumentado com o `EngineTracer` da própria instrumentação, que só registra listeners naquele engine. A chamada fica em `main.create_app()`, logo depois de criar o engine, e não dentro de `db.get_engine()`, que tem impacto CRITICAL no GitNexus (317 dependentes).

As convenções HTTP estáveis (`OTEL_SEMCONV_STABILITY_OPT_IN=http`, por `setdefault`) dão atributos separados (`url.path`, `url.query`, `http.request.method`), o que simplifica a sanitização (D3). O APM Server 9.5 já mapeou esses atributos no traço de teste.

### D2. Sampler que descarta span raiz de cliente

O sampler é `ParentBased`, e a regra para spans raiz é esta: span de kind `CLIENT` sem pai é descartado; o resto é amostrado.

- **O que ele corta:** consultas e chamadas httpx de trabalho em segundo plano (reconciliação, timers, handlers do websocket da UI). Sem a regra, cada uma vira um "traço" de um span só e polui a lista de transações do APM.
- **O que ele mantém:**
  - o `agent.run`, que é `INTERNAL`;
  - os spans de servidor;
  - os filhos de `agent.run`, que têm pai remoto explícito.

Alternativa descartada: filtrar no Collector. O lixo sairia do processo, e a regra dependeria de reconstruir o traço no Collector.

Achado na verificação ao vivo: os timers que o NiceGUI cria ao montar uma página são tarefas asyncio que copiam o contexto da requisição. Cada consulta periódica deles virava filha da transação da página, muito depois de ela ter terminado (922 consultas num único `GET /systems/{system_id}`). Por isso, o sampler ganhou mais uma regra: span cujo pai local já terminou não é amostrado. Pai remoto (`traceparent`, `parent_context_for_run`) não tem fim conhecido e segue a regra normal.

Junto disso, `start_run_root_span` passa a abrir o span com um contexto vazio explícito. Hoje ser raiz depende de a thread não herdar contexto. No Python 3.14 com free-threading a thread herda, e o `agent.run` viraria filho de outra coisa, quebrando a correlação com o broker.

### D3. Sanitização no exporter, na origem

O exporter OTLP de traços é envolvido por um exporter que, antes de enviar:
- remove `url.query`;
- tira a query de `url.full`, e de `http.url`/`http.target` se a semconv antiga aparecer.

Cabeçalhos e corpos não são capturados, que é o padrão das instrumentações, e nenhuma variável `OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*` é ligada.

- Alternativa descartada, só no Collector: o `code` do OIDC já teria saído do processo.
- Alternativa descartada, hooks das instrumentações: cada instrumentação tem o seu, e o atributo nasce antes do hook em algumas delas.

O exporter Postgres não precisa disso: ele só persiste spans com `run_id`, e os spans automáticos não têm.

### D4. Métricas com temporalidade cumulativa no SDK, e delta no Collector do Elastic

- **No processo:** um `MeterProvider` com leitor periódico e exporter OTLP HTTP, só se `APPAIFORGE_OTEL_METRICS_ENDPOINT` estiver definida. O intervalo é o padrão do SDK, ajustável por `OTEL_METRIC_EXPORT_INTERVAL`.
- **Origem das métricas:**
  - HTTP vem das instrumentações FastAPI e httpx;
  - pool vem da instrumentação SQLAlchemy;
  - CPU e memória vêm de `system-metrics`, limitada às métricas `process.*`.
- **Temporalidade:**
  - o SDK fica no padrão cumulativo, que é o que o Prometheus espera;
  - o pipeline de métricas do Collector Elastic usa o processor `cumulativetodelta`, porque o APM Server trata melhor as métricas delta, sobretudo histogramas;
  - assim, a particularidade do Elastic fica no Collector, como pede o ADR 0025.
- **Alternativas descartadas:**
  - delta no SDK quebraria o perfil Grafana;
  - uma variável de temporalidade por backend no app viola o ADR 0025.
- **Perfil Grafana:** o Collector expõe o exporter `prometheus` em `:8889`, e o `prometheus.yml` ganha um job `otel-collector`. Quando o perfil `observability` não está de pé, o alvo só fica `down`.

### D5. Resource: padrões do código, ambiente pelo operador

O resource é montado com:
- `service.name`: `appaiforge-portal` ou `appaiforge-broker`, como hoje;
- `service.version` = `__version__`;
- `service.instance.id` = UUID gerado por processo.

Depois, é mesclado com o `OTELResourceDetector`, para `OTEL_RESOURCE_ATTRIBUTES` e `OTEL_SERVICE_NAME` prevalecerem. Hoje `Resource.create(attrs)` faz o contrário: os valores do código ganham do ambiente. O mesmo resource vale para traços, métricas e logs.

Não foi criada uma variável `APPAIFORGE_ENVIRONMENT` própria: `OTEL_RESOURCE_ATTRIBUTES` já é o padrão e o chart pode preenchê-la.

### D6. Chamada ao LiteLLM sob `llm.request`

No broker, o encaminhamento roda com `llm.request` como span corrente. Assim, o span httpx da chamada ao LiteLLM nasce filho dele, no traço da execução, e não no traço da requisição HTTP recebida.

O span `llm.request` hoje termina quando a resposta começa, e não quando o streaming acaba. O span httpx herda esse limite. Medir o streaming inteiro está fora do escopo.

### D7. Compose: Elastic 9.5.6 e destino configurável

- **Versões:** `elasticsearch`, `kibana` e `apm-server` vão para 9.5.6. Os argumentos `apm-server.kibana.*` do APM Server são revistos contra o 9.5.6.
- **Destino do exporter:** passa a ser `${env:APM_SERVER_ENDPOINT:-apm-server:8200}`.
- **Para mandar a um Elastic externo**, como o de teste em `172.30.0.6`, sobe-se só o Collector:

  ```
  APM_SERVER_ENDPOINT=172.30.0.6:8200 docker compose --profile observability-elastic up -d --no-deps otel-collector-elastic
  ```

  com os endpoints OTEL do portal e do broker apontando para `otel-collector`.

Token e TLS do Elastic de produção ficam para a change do chart, onde mora o Secret.

## Risks / Trade-offs

- **[Página do NiceGUI sem `http.route`]:** o NiceGUI é montado como sub-app, e a transação pode sair só como `GET`, sem o caminho agrupado. → Verificar ao vivo. Se acontecer, usar o hook de servidor para nomear pela rota do NiceGUI.
- **[Ações da UI invisíveis]:** cliques chegam pelo websocket e não geram span de servidor; suas consultas são descartadas pelo D2. → Aceito e documentado na ADR. Instrumentar eventos do NiceGUI é trabalho à parte.
- **[Volume no `BatchSpanProcessor`]:** a fila do exporter Postgres passa a receber todos os spans, embora descarte os que não têm `run_id`. → O custo é uma checagem de atributo. Se a fila encher, os spans do Debug log podem cair. A tarefa de verificação confere isso sob carga leve.
- **[Compatibilidade das instrumentações]:** as instrumentações `0.66b*` precisam casar exatamente com o SDK 1.45. → Fixar a mesma série no `pyproject`.
- **[Sintaxe de default no Collector 0.112]:** `${env:VAR:-default}` precisa ser suportada nessa versão. → Verificar. Se não for, subir o Collector.
- **[ES 9.5.6 com 512 MB de heap no compose]:** pode não subir. → Verificar e ajustar `ES_JAVA_OPTS`.

## Migration Plan

1. Quem usa o perfil `observability-elastic`:

   ```
   docker compose --profile observability-elastic down
   docker volume rm <projeto>_elasticsearchdata
   ```

   Depois, subir de novo. O ES 9 não abre o volume do 8.15 sem passar pelo 8.19, e são dados de exemplo.
2. Portal e broker: nenhuma variável nova é obrigatória. As métricas só ligam com `APPAIFORGE_OTEL_METRICS_ENDPOINT`.
3. Rollback: voltar a imagem do portal desliga a instrumentação. No compose, voltar as versões exige apagar o volume de novo.

## Open Questions

- `__version__` parado em `0.1.0` deixa `service.version` sem sentido até alguém defini-lo por `OTEL_RESOURCE_ATTRIBUTES`. A change do chart deve preencher com a tag da imagem. Alinhar `__version__` com as releases é um follow-up independente.
