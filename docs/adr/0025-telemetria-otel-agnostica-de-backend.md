# 0025 — Telemetria OTel agnóstica de backend; Debug log e auditoria do gate continuam separados

* Status: aceito
* Data: 2026-11-09
* Decidida em: changes `agent-telemetry-otel` e `agent-telemetry-backend-agnostic` (etapa 6 do
  roadmap de confinamento)
* Relacionada: [ADR 0017](0017-gate-de-operacoes-destrutivas-com-classificador-sql.md) (`GateDecision`,
  que esta ADR explicitamente mantém intacto); [ADR 0020](0020-broker-de-inferencia-com-litellm.md)
  (de onde vem o `run_id` resolvido no broker, usado para correlacionar `llm.request`)

## Contexto

O roadmap previa a etapa 6 como um pipeline único de telemetria (OTel → Collector → Prometheus +
Tempo + Loki → Grafana) do qual o Debug log do chat e a página de auditoria do gate passariam a
ser *views*, substituindo o pipeline próprio de cada um. A primeira change (`agent-telemetry-otel`)
entregou o span tree por execução (`agent.run` com filhos `db.query`/`tool.*`/`policy.decision`/
`llm.request`, correlacionados por `run_id` via um gerador de ID determinístico que permite ao
broker — processo separado do portal — reconstruir o span pai sem chamada de rede nova) e os logs
estruturados, mas com o Debug log consultando a API REST do Tempo diretamente e o endpoint de
exportação apontando direto para Tempo/Loki.

Durante exploração posterior, o operador levantou que o produto deve ser agnóstico de tecnologia —
o cliente que implanta o sistema deveria poder escolher seu próprio backend de observabilidade
(Grafana, Elastic, ou outro) sem o portal/broker saberem qual foi escolhido. Isso expôs dois
acoplamentos que a primeira change deixou: o endpoint de exportação apontava direto a um backend
específico, e o Debug log dependia da API de consulta proprietária do Tempo.

## Decisão

**Exportação sempre via um OTel Collector com endpoint fixo.** `APPAIFORGE_OTEL_TRACES_ENDPOINT`/
`APPAIFORGE_OTEL_LOGS_ENDPOINT` nunca apontam para um backend específico — apontam para um
Collector cuja própria configuração decide o destino final (Tempo/Loki, Elasticsearch/APM Server,
ou outro). Dois profiles de exemplo no `docker-compose.yml` (`observability` e
`observability-elastic`) provam a troca concreta: verificado ao vivo que apontar o Collector para
um backend diferente faz o mesmo span aparecer no novo backend sem nenhuma mudança de código ou de
configuração da aplicação.

**Debug log lê de uma tabela Postgres própria, não de um backend de observabilidade.** Um
`SpanProcessor` próprio (`_PostgresSpanExporter`, dentro de um `BatchSpanProcessor` — reaproveita a
fila/thread de background já pronta do SDK, best-effort por span) persiste cada span finalizado em
`agent_telemetry_spans`, compartilhada entre portal e broker. O Debug log passa a consultar essa
tabela, nunca Tempo/Elasticsearch/etc. — funciona mesmo sem nenhum backend de observabilidade
externo configurado. Retenção por TTL (`APPAIFORGE_OTEL_SPAN_RETENTION_DAYS`, default 30 dias) via
`app.timer` no boot do portal.

**`GateDecision` e `ManagementAudit` NÃO viram views sobre a telemetria — decisão explícita,
divergindo do plano original da etapa 6.** Se a página de auditoria do gate dependesse do backend
de observabilidade, trocar de Grafana para Elastic (ou desligar o stack) quebraria a trilha de
compliance. Os dois continuam como fonte de verdade independente, gravados em Postgres como
sempre, sem nenhuma chamada nova de telemetria alterando esse comportamento — verificado ao vivo
que a aba "Auditoria" continua idêntica.

## Alternativas consideradas

- **Endpoint de exportação apontando direto ao backend escolhido, documentando a troca de URL** —
  tecnicamente funcionaria (OTLP já é aceito nativamente por Tempo, Loki e Elastic APM Server), mas
  deixaria a aplicação "sabendo" implicitamente que existe um backend específico atrás de cada URL,
  e impediria fan-out (exportar para dois backends ao mesmo tempo) sem duplicar exporters na própria
  aplicação. Descartada em favor do Collector.
- **Filebeat como camada de "log agnóstico"** — descartada: Filebeat transporta arquivos para
  Elasticsearch/Logstash, não fala OTLP, não carrega `trace_id` nativamente, e colocá-lo ao lado do
  exporter OTLP já existente criaria dois caminhos paralelos emitindo a mesma linha de log.
- **Dual-write explícito em cada call site de instrumentação** (gravar em Postgres e emitir span
  OTel em duas chamadas separadas) — descartada: duplica código em todo ponto de instrumentação
  existente e futuro. Preferido um `SpanProcessor` adicional no mesmo `TracerProvider`, cobrindo
  automaticamente qualquer span criado pelo ponto de criação já existente.
- **Postgres como fonte única, com exportação derivada por job separado** — descartada: adiciona uma
  pipeline de exportação com lag/batching sem ganho claro, já que o `BatchSpanProcessor` de
  exportação já resolve isso de forma independente.

## Consequências

- Trocar o backend de observabilidade é operação de infraestrutura (config do Collector + qual
  profile está de pé), nunca de código ou deploy da aplicação.
- Debug log fica com uma tabela própria em Postgres para manter (`agent_telemetry_spans`, com
  retenção por TTL nova para o projeto — nenhuma outra tabela do portal tem limpeza automática
  hoje; escopo estritamente limitado a essa tabela).
- Um span órfão (sem `AgentRun` correspondente) é isolado por linha na persistência — achado ao
  vivo durante a implementação: gravar o lote inteiro numa única transação (`add_all`) fazia um
  span órfão derrubar o commit de spans válidos do mesmo lote.
- O profile `observability-elastic` dobra a superfície de infraestrutura de exemplo que o projeto
  mantém — aceito como exemplo de referência, não como caminho de produção continuamente
  monitorado.
- Prometheus continua subindo no profile `observability`, mas sem instrumentação de métricas real —
  ficou de fora do escopo desta etapa (ver roadmap, próxima exploração).
