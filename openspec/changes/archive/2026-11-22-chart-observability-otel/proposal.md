# Proposal

## Why

A v1.8.0 deixou o portal falando OTLP completo, mas só no compose. Instalado pelo chart Helm, o portal não recebe nenhuma variável OTEL, e não existe Collector no cluster. Em produção no Kubernetes, nada é exportado. O README do chart ainda diz que a telemetria está fora do escopo.

Esta é a segunda de três changes de observabilidade (portal, chart, borda das apps). O destino de referência é um Elastic próprio do operador, fora do cluster, recebendo por um APM Server standalone, como o ambiente de teste validado na change anterior.

## What Changes

- **Collector no chart, desligado por padrão.** Com `observability.enabled=true`, o chart sobe um OTel Collector (Deployment, Service e ConfigMap) que recebe OTLP do portal e do Traefik. Ele repassa a um endpoint OTLP externo, por padrão um APM Server, com as métricas convertidas para delta.
- **Credencial só do Collector.** Token ou API key, mais uma CA opcional, vêm de um Secret criado fora do Helm (`existingSecret`) e montado só no Collector. O portal nunca recebe essa credencial.
- **Portal apontado para o Collector.** O chart passa `APPAIFORGE_OTEL_TRACES_ENDPOINT`, `_LOGS_ENDPOINT` e `_METRICS_ENDPOINT` com o endereço do Service do Collector. Também passa `OTEL_RESOURCE_ATTRIBUTES` com:
  - `service.version` igual à tag da imagem;
  - o ambiente da instalação;
  - o Pod e o namespace.
- **Traefik do subchart com traços e métricas OTLP** mandados ao Collector, ligáveis à parte. A query string já sai mascarada pelo Traefik.
- **Métricas de CPU e memória dos Pods (`kubeletstats`), desligadas por padrão.** Ligadas, sobem um Collector por nó (DaemonSet) e um `ClusterRole` só com leitura das estatísticas do kubelet. As métricas são marcadas com o sistema dono do Pod, a partir dos labels `appaiforge.slug` e `appaiforge.system_id`, e seguem pelo Collector central.
- **Saída para outro backend.** O operador pode substituir a configuração inteira do Collector central, ou apontar o portal para um Collector que já exista no cluster, sem o chart criar o dele.
- **Docs:**
  - README do chart, com valores, Secret e o que continua de fora;
  - nova ADR 0034;
  - `docs/driver-kubernetes.md`.
- **Fora do escopo:**
  - o broker continua fora do chart, e a change só documenta como apontá-lo para o Collector;
  - a borda das apps por sistema (`/apps/<slug>` como serviço próprio) é a terceira change.

Nada muda para quem não liga `observability.enabled`: o render padrão do chart continua o mesmo.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `service-observability`: ganha requisitos de instalação no Kubernetes:
  - o Collector opcional do chart;
  - o Secret só do Collector;
  - as variáveis OTEL e a identificação do portal;
  - o tracing do Traefik;
  - as métricas de recursos por Pod marcadas pelo sistema.

  São requisitos novos, sem mudar os atuais.

## Impact

- **Chart (`deploy/helm/appaiforge-portal`):**
  - `values.yaml`: bloco `observability`, e `traefik.tracing`/`traefik.metrics` pré-preenchidos e desligados;
  - templates novos para os dois Collectors, com ConfigMap, Service, RBAC e ServiceAccount;
  - env novo em `deployment.yaml` e validações em `_helpers.tpl`.
- **Testes:** `portal/tests/unit/test_helm_chart.py`, renderizando com `helm template`.
- **Imagem nova no chart:** `otel/opentelemetry-collector-contrib`, na mesma versão do compose.
- **RBAC:** o primeiro `ClusterRole` do chart fora do namespace (`nodes/stats`), só com `kubeletstats` ligado. O `ClusterRole` de namespaces que já existe não muda.
- **Código do portal:** nenhum.
- **Verificação:** um cluster kind descartável, montado pelo README do piloto e mandando para o APM Server de teste. Só com autorização do operador antes de criar ou mexer em cluster.
