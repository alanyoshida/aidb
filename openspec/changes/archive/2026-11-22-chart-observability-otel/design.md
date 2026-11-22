# Design

## Context

- **O chart (`deploy/helm/appaiforge-portal`) não tem nada de telemetria.** O `deployment.yaml` não passa variáveis OTEL, e o README diz que a telemetria está fora do escopo. O portal da v1.8.0 já exporta traços, métricas e logs quando recebe `APPAIFORGE_OTEL_*_ENDPOINT`, e aceita `OTEL_RESOURCE_ATTRIBUTES`.
- **Padrões que o chart já segue:**
  - Secrets externos por `existingSecret`;
  - validações com `fail` em `_helpers.tpl`;
  - testes em `portal/tests/unit/test_helm_chart.py` com `helm template`;
  - um `ClusterRole` só para `namespaces` (`rbac.clusterScoped`).
- **Traefik do subchart (42.3.2, Traefik v3.7.17).** Já suporta `tracing.otlp` e `metrics.otlp`, e mascara a query string nos traços por padrão (`safeQueryParams: []`). Os valores do subchart são estáticos: não aceitam template, então não dá para calcular dentro deles o nome do Service do Collector.
- **Pods de sistema.** Têm os labels `appaiforge.slug` e `appaiforge.system_id`, e rodam no namespace de sistemas (`portal.systemsNamespace`, por padrão o da release).
- **Compose.** Já usa o Collector contrib 0.112.0 com `cumulativetodelta` para o APM Server. O chart reaproveita a mesma versão e o mesmo pipeline.
- **Destino de referência.** O APM Server standalone 9.5.6 do Elastic próprio do operador. O de teste fica em `172.30.0.6:8200`, sem security.

## Goals / Non-Goals

**Goals:**
- ligar a observabilidade de uma instalação Kubernetes com poucos valores e sem mexer no portal;
- credencial do destino isolada no Collector;
- CPU e memória por sistema no cluster, equivalente ao que o cAdvisor dá no Docker;
- render padrão do chart inalterado.

**Non-Goals:**
- `service.name` por app e spans da borda `/apps/<slug>` como serviço (terceira change);
- broker no chart;
- Elastic dentro do cluster (ECK);
- `k8s_cluster`, eventos e logs de nó;
- alta disponibilidade do Collector (uma réplica).

## Decisions

### D1. Valores num bloco `observability`, desligado por padrão

```yaml
observability:
  enabled: false
  environment: ""            # deployment.environment
  collector:
    create: true             # false = usar um Collector existente
    endpoint: ""             # base OTLP/HTTP do Collector existente (create=false)
    image: { repository: otel/opentelemetry-collector-contrib, tag: "0.112.0" }
    resources: {}
    config: ""               # YAML completo que substitui o gerado
  exporter:
    endpoint: ""             # destino OTLP, ex.: apm.exemplo.com:8200
    insecure: false          # sem TLS (APM Server de teste)
    deltaMetrics: true       # cumulativetodelta antes de exportar (APM Server)
    existingSecret: ""       # Secret do destino, lido só pelo Collector central
    token: true              # usa a chave `token` no cabeçalho Authorization
    authScheme: Bearer       # Bearer (secret_token) ou ApiKey
    ca: false                # usa a chave `ca.crt` como CA do destino
  kubeletstats:
    enabled: false
    insecureSkipVerify: false
    collectionInterval: 30s
```

O Collector central não sabe que o destino é o Elastic. Ele exporta OTLP gRPC para `exporter.endpoint`. `deltaMetrics` existe porque o APM Server trata melhor métricas delta. Para outro backend, o operador desliga essa opção ou passa uma `config` própria.

Alternativa descartada: valores com o nome do Elastic (`elastic.apmServer...`). Amarraria o chart a um backend, contra o ADR 0025.

### D2. Credencial por expansão de variáveis no Pod do Collector

- **Token.** O Secret de `exporter.existingSecret` vira a variável `EXPORTER_TOKEN` (`secretKeyRef`, `optional: true`). Uma segunda variável, `EXPORTER_AUTHORIZATION`, recebe `"<authScheme> $(EXPORTER_TOKEN)"`, pela expansão `$(VAR)` do Kubernetes. A configuração gerada usa `headers: { Authorization: ${env:EXPORTER_AUTHORIZATION} }`.
- **CA.** A chave `ca.crt`, se existir, é montada como arquivo (`items` com `optional: true`) e referenciada em `tls.ca_file`.
- **Isolamento.** O Secret só aparece no Pod do Collector central. O DaemonSet do `kubeletstats` e o portal não o referenciam.
- **Sem Secret.** O cabeçalho não é gerado.

Achado na implementação: as chaves do Secret não podem ser opcionais de verdade. Com `optional: true`, uma chave ausente faria o Collector mandar `Bearer ` vazio, ou procurar uma CA que não existe e falhar ao subir. Por isso, o uso de cada chave é explícito (`exporter.token` e `exporter.ca`), e as referências ao Secret não são opcionais: um Secret sem a chave declarada impede o Pod de subir, com o motivo no evento.

Alternativa descartada: a extensão `bearertokenauth` do Collector. Ela não monta o esquema `ApiKey` da Elastic, e exigiria dois caminhos.

### D3. Endpoints e identificação passados ao portal

- **Endpoints.** Com `observability.enabled`, o portal recebe `APPAIFORGE_OTEL_{TRACES,METRICS,LOGS}_ENDPOINT` = `<base>/v1/{traces,metrics,logs}`. A `<base>` é o Service do Collector do chart, `http://<fullname>-otel-collector.<ns>.svc.cluster.local:4318`, ou `collector.endpoint` quando `create=false`.
- **Identificação.** O portal recebe também `POD_NAME` e `POD_NAMESPACE`, pela downward API, e `OTEL_RESOURCE_ATTRIBUTES` com:
  - `service.version` igual a `image.tag`;
  - `deployment.environment`, só se `environment` estiver definido;
  - `k8s.pod.name=$(POD_NAME)`;
  - `k8s.namespace.name=$(POD_NAMESPACE)`.

Isso fecha a questão aberta da change anterior: no cluster, `service.version` passa a ser a tag da imagem, e não o `__version__` parado do pacote.

### D4. Traefik: endpoint pré-preenchido no subchart e conferido pelo chart pai

`values.yaml` traz `traefik.tracing.otlp` e `traefik.metrics.otlp` desligados, com `http.endpoint` já apontando para `http://appaiforge-portal-otel-collector:4318/v1/{traces,metrics}`. É o Service com o `fullnameOverride` padrão, e o nome curto funciona porque o Traefik do subchart está no namespace da release.

O operador liga com `traefik.tracing.otlp.enabled=true` e `traefik.tracing.otlp.http.enabled=true` (o mesmo vale para métricas).

O chart pai confere os valores do subchart e recusa renderizar em dois casos:
- tracing ou métricas do Traefik ligados com `observability.enabled=false`;
- `collector.create=true` e o endpoint do Traefik não contém o nome do Service do Collector desta instalação. Isso pega um `fullnameOverride` diferente sem o endpoint ajustado.

Alternativa descartada: passar a configuração ao Traefik por `additionalArguments` gerados no chart pai. Os valores do subchart também são estáticos aí, então o problema seria o mesmo.

### D5. `kubeletstats` num DaemonSet, com permissões mínimas

Com `kubeletstats.enabled`, o chart cria um DaemonSet de Collector "agente", com:
- **Receiver** `kubeletstats`: `auth_type: serviceAccount`, `endpoint: https://${env:K8S_NODE_IP}:10250` (IP do nó pela downward API: o nome do nó não resolve pelo DNS do cluster no kind), grupos `pod` e `container`, e `insecure_skip_verify` conforme o valor (o kind usa certificado autoassinado no kubelet).
- **Processors:**
  - `filter`, que mantém só os namespaces da release e dos sistemas;
  - `k8sattributes`, que extrai os labels `appaiforge.slug` e `appaiforge.system_id` do Pod, com um processor por namespace (cada um com `filter.namespace`);
  - `transform`, que define `service.name` como o slug, nos Pods de sistema, ou `appaiforge-portal`, no Pod do portal.
- **Exporter:** `otlphttp` para a mesma base usada pelo portal. Assim as métricas passam pelo Collector central e recebem o mesmo tratamento.
- **RBAC:**
  - `ClusterRole` com `nodes/stats` e `nodes` em `get`, o único acesso fora do namespace;
  - `Role` com `pods` em `get`/`list`/`watch` no namespace da release e no de sistemas.

  ServiceAccount próprio, sem o token do portal.

Por que um DaemonSet: o kubelet só expõe as estatísticas dos Pods do próprio nó. Um Deployment veria um nó só, e os Pods de sistema podem estar em qualquer nó.

Por que `service.name` igual ao slug: a terceira change vai pôr os traços da borda de cada app sob o mesmo nome. No APM, cada sistema fica como um serviço só, com traços e recursos juntos.

Alternativa descartada: um `ClusterRole` com `pods` em `list`/`watch` no cluster inteiro. Seria mais simples, mas daria acesso de leitura a Pods de outros namespaces sem necessidade.

### D6. Collector central como Deployment com configuração gerada

- **Recursos:** Deployment de uma réplica, Service com 4317/4318 e ConfigMap.
- **Pipelines** (`memory_limiter` e `batch` em todos):
  - traços e logs: `otlp` → exporter;
  - métricas: `otlp` → `cumulativetodelta` (com `deltaMetrics`) → exporter.
- **Configuração própria:** `collector.config` substitui o ConfigMap inteiro. As variáveis do Secret continuam disponíveis para o operador usar.
- **Segurança:** a imagem contrib roda sem root. O chart define `readOnlyRootFilesystem` e não monta o token do ServiceAccount, porque o central não fala com a API do Kubernetes.

### D7. Broker continua fora do chart

O README do chart passa a dizer como apontar um broker implantado à parte para o Collector: `APPAIFORGE_OTEL_TRACES_ENDPOINT` e `_METRICS_ENDPOINT` com o FQDN do Service.

## Risks / Trade-offs

- **[Endpoint do Traefik estático]:** se o operador mudar `fullnameOverride` ou desligar `collector.create`, precisa ajustar o endpoint do Traefik à mão. → O chart confere e recusa renderizar com o endereço errado. O README documenta.
- **[Certificado do kubelet]:** em cluster gerenciado o certificado costuma ser válido, mas no kind não é. → `insecureSkipVerify` fica desligado por padrão, e o README e os valores do piloto mostram quando ligar.
- **[Volume de métricas]:** com intervalo de 30 s, `kubeletstats` gera séries por Pod e por container. → Os grupos ficam restritos a `pod` e `container`, e o filtro limita aos namespaces da instalação.
- **[Token só testável com APM Server autenticado]:** o APM Server de teste não tem `secret_token`, então aceita qualquer cabeçalho. → O teste do chart confere o cabeçalho montado. A verificação ao vivo da autenticação depende de o operador ligar o `secret_token` no ambiente de teste, e fica como tarefa opcional.
- **[Rede do kind até o Elastic externo]:** o Pod do Collector precisa alcançar `172.30.0.6:8200` saindo pelo nó do kind. → A primeira tarefa da verificação testa isso antes de instalar.

## Migration Plan

1. Atualizar o chart sem mudar valores: o render é o mesmo, então nada acontece.
2. Para ligar: definir `observability.enabled=true`, `observability.exporter.endpoint` e, se houver credencial, criar o Secret antes e indicar em `existingSecret`. Fazer `helm upgrade`: o portal reinicia com as variáveis novas.
3. Para ligar os traços do Traefik: `traefik.tracing.otlp.enabled=true` e `traefik.tracing.otlp.http.enabled=true`. O Traefik reinicia (rollout `maxSurge: 0` no piloto).
4. Para ligar recursos por Pod: `observability.kubeletstats.enabled=true`. Isso cria o `ClusterRole` de `nodes/stats`.
5. Rollback: desligar os valores e fazer `helm upgrade`. Os recursos do Collector somem, e o portal volta a não exportar.

## Open Questions

- **Métricas de recursos (ADR 0026).** No Docker, CPU e memória por sistema vão ao Prometheus pelo cAdvisor. No cluster, esta change as manda ao destino OTLP. Unificar num backend só, ou manter os dois caminhos, fica para quando o operador escolher o backend de métricas de produção. Isso não muda o chart desta change: um Prometheus pode ser apontado por `collector.config`.
