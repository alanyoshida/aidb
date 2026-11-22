# 0034 — Observabilidade no chart Kubernetes: Collector opcional, credencial só nele e recursos por sistema pelo kubelet

* Status: aceito
* Data: 2026-11-22
* Decidida em: change `chart-observability-otel` (segunda de três: portal, chart, borda das apps)
* Relacionada: [ADR 0025](0025-telemetria-otel-agnostica-de-backend.md) (o portal só conhece o
  Collector); [ADR 0026](0026-metricas-de-recursos-por-container-via-cadvisor.md) (recursos por
  sistema no Docker, pelo cAdvisor); [ADR 0033](0033-auto-instrumentacao-do-portal-e-elastic-apm.md)
  (o que o portal emite)

## Contexto

A v1.8.0 deixou o portal exportando traços, métricas e logs por OTLP, mas só o compose passava as
variáveis. Instalado pelo chart Helm, o portal não exportava nada, e o cluster não tinha Collector.
O destino de referência do operador é um Elastic próprio, fora do cluster, recebendo por um APM
Server standalone.

## Decisão

**Collector central opcional no chart, agnóstico de backend.** Com `observability.enabled`, o chart
sobe um Collector (Deployment, Service e ConfigMap) que recebe OTLP e repassa a
`observability.exporter.endpoint`. Os valores não citam o Elastic. A conversão das métricas para
delta, que o APM Server pede, é uma opção (`deltaMetrics`) ligada por padrão. Uma configuração
completa do operador (`collector.config`) substitui a gerada, para outro backend. Sem
`observability.enabled`, o render do chart é o mesmo de antes.

**Credencial do destino só no Collector central.** Token e CA vêm de um Secret criado fora do Helm.
O cabeçalho `Authorization: <Bearer|ApiKey> <token>` é montado no Pod pela expansão `$(VAR)` do
Kubernetes. O portal, o Traefik e o agente de kubeletstats não referenciam o Secret. O uso de cada
chave (`token`, `ca`) é explícito, porque uma chave opcional ausente faria o Collector mandar um
cabeçalho vazio ou procurar uma CA que não existe.

**O portal recebe endpoints e identidade.** Os três `APPAIFORGE_OTEL_*_ENDPOINT` apontam para o
Service do Collector, ou para um Collector existente. `OTEL_RESOURCE_ATTRIBUTES` leva
`service.version` igual à tag da imagem (no cluster, isso substitui o `__version__` parado do
pacote), o ambiente, o Pod e o namespace.

**Traefik com endpoint pré-preenchido e conferido.** Os valores do subchart não aceitam template.
O endpoint OTLP do Traefik vem escrito com o Service do Collector no `fullnameOverride` padrão, e o
chart pai recusa renderizar quando ele não aponta para o Collector desta instalação.

**Recursos por Pod pelo kubelet, num DaemonSet.** O kubelet só expõe as estatísticas dos Pods do
próprio nó, e os Pods de sistema podem estar em qualquer nó. Com `kubeletstats.enabled`, um
Collector por nó lê o kubelet, filtra os namespaces da instalação, marca cada Pod com o slug e o id
do sistema (`k8sattributes`) e manda ao Collector central. `service.name` vira o slug do sistema,
o mesmo nome que a borda das apps vai usar. Permissões: um `ClusterRole` só com `get` em
`nodes/stats` e `nodes`, e a leitura de Pods em `Role` por namespace, sem `ClusterRole` de pods.

## Alternativas consideradas

- **Valores com o nome do Elastic (`elastic.apmServer...`)** — descartada: amarraria o chart a um
  backend, contra o ADR 0025.
- **Extensão `bearertokenauth` do Collector** — descartada: não monta o esquema `ApiKey` da Elastic.
- **`kubeletstats` no Collector central (Deployment)** — descartada: veria um nó só.
- **`ClusterRole` com leitura de Pods no cluster inteiro** — descartada: mais simples, mas daria
  acesso a Pods de outros namespaces sem necessidade.
- **Configurar o Traefik por argumentos gerados no chart pai** — descartada: também são valores do
  subchart, então o problema do valor estático seria o mesmo.

## Consequências

- Com outro `fullnameOverride`, o operador ajusta o endpoint do Traefik à mão. O chart avisa.
- No kind, o kubelet tem certificado autoassinado e pede `kubeletstats.insecureSkipVerify`. Num
  cluster gerenciado, o padrão (`false`) vale.
- Recursos por sistema passam a ter dois caminhos: Prometheus pelo cAdvisor no Docker (ADR 0026) e o
  destino OTLP no cluster. Unificar fica para quando o operador escolher o backend de métricas de
  produção.
- O broker continua fora do chart. Implantado à parte, ele aponta para o Service do Collector.
- O agente liga o feature gate `receiver.kubeletstats.enableCPUUsageMetrics`: CPU sai como uso em
  núcleos (`k8s.pod.cpu.usage`), não como a `*.cpu.utilization` que o `kubeletstats` 0.112 marca
  como obsoleta. Verificado num cluster kind contra o APM Server 9.5.6 de teste.
