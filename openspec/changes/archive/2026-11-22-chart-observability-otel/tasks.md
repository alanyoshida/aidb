# Tasks

## 1. Valores e validações

- [x] 1.1 Adicionar o bloco `observability` ao `values.yaml` (design D1), com comentários no padrão do arquivo. Pré-preencher, desligados, `traefik.tracing.otlp` e `traefik.metrics.otlp` com o endpoint do Service padrão (design D4). Verificar com teste em `test_helm_chart.py`: o render com os valores padrão não tem nenhum recurso de Collector nem variável `APPAIFORGE_OTEL_*`/`OTEL_RESOURCE_ATTRIBUTES` no portal, igual ao render anterior.
- [x] 1.2 Validações em `_helpers.tpl` (design D1 e D4), com mensagem que diga o que falta. Verificar com testes, um por caso, que o render falha com a mensagem certa nestes casos:
  - observabilidade ligada sem `exporter.endpoint` e sem `collector.config`;
  - `create=false` sem `collector.endpoint`;
  - tracing ou métricas do Traefik ligados com a observabilidade desligada;
  - endpoint do Traefik que não aponta para o Service do Collector desta instalação.

## 2. Collector central

- [x] 2.1 Templates do Collector central (design D6): Deployment, Service (4317/4318) e ConfigMap com a configuração gerada. Usar `collector.config` quando definido, e o `cumulativetodelta` só com `deltaMetrics`. Verificar com testes:
  - a configuração gerada tem os três pipelines e o exporter apontando para `exporter.endpoint`;
  - `deltaMetrics=false` tira o `cumulativetodelta`;
  - `collector.config` substitui o conteúdo do ConfigMap;
  - o Pod não monta o token do ServiceAccount e roda com `readOnlyRootFilesystem`.
- [x] 2.2 Credencial (design D2): `EXPORTER_TOKEN` por `secretKeyRef` opcional, `EXPORTER_AUTHORIZATION` com o esquema, cabeçalho e `ca_file` só quando há `existingSecret`. Verificar com testes:
  - com Secret, o Pod do Collector referencia o Secret e a configuração tem o cabeçalho `Authorization` e o `ca_file`;
  - sem Secret, nenhum dos dois aparece;
  - nenhum outro recurso do render referencia o Secret.

## 3. Portal e Traefik

- [x] 3.1 Variáveis do portal em `deployment.yaml` (design D3): os três endpoints com a base do Collector do chart ou de `collector.endpoint`, `POD_NAME`/`POD_NAMESPACE` pela downward API, e `OTEL_RESOURCE_ATTRIBUTES` com `service.version`, `deployment.environment` (se definido), `k8s.pod.name` e `k8s.namespace.name`. Verificar com testes:
  - com a imagem `1.9.0` e o ambiente `producao`, as variáveis têm os valores esperados e `POD_NAME` vem antes de `OTEL_RESOURCE_ATTRIBUTES`;
  - com `create=false`, os endpoints usam o `collector.endpoint`.
- [x] 3.2 Traefik (design D4): confirmar com `helm template` que ligar `traefik.tracing.otlp` passa ao Deployment do Traefik o argumento de tracing OTLP com o endpoint do Collector. Verificar com teste que o argumento aparece só quando ligado.

## 4. Recursos por Pod (`kubeletstats`)

- [x] 4.1 DaemonSet agente, ConfigMap, ServiceAccount, `ClusterRole` e `ClusterRoleBinding` de `nodes/stats`/`nodes`, e `Role`/`RoleBinding` de `pods` nos namespaces da release e de sistemas (design D5). O ConfigMap leva `kubeletstats`, `filter`, um `k8sattributes` por namespace, `transform` e `otlphttp`. Verificar com testes:
  - nada disso aparece com `kubeletstats.enabled=false`;
  - ligado, o `ClusterRole` só tem `get` em `nodes/stats` e `nodes`;
  - com `systemsNamespace` diferente do da release, há uma `Role` em cada um e dois `k8sattributes`;
  - o DaemonSet não referencia o Secret do exporter.

## 5. Documentação

- [x] 5.1 README do chart:
  - seção de observabilidade com os valores, o Secret (chaves `token` e `ca.crt`) e como ligar o Traefik e o `kubeletstats`;
  - como apontar um broker implantado à parte para o Collector (design D7);
  - tirar a frase que diz que a telemetria está fora do escopo.

  Em `docs/driver-kubernetes.md`, um parágrafo com o link. Verificar que nenhuma doc ainda diz que o chart não cobre telemetria (`grep -rn "telemetria" deploy/helm docs/driver-kubernetes.md`).
- [x] 5.2 ADR 0034 com as decisões D1 a D6, a questão aberta das métricas de recursos (ADR 0026) e o índice em `docs/adr/README.md`. Mais uma nota de atualização na ADR 0033, apontando que no cluster `service.version` vem da tag. Verificar que o índice lista a ADR nova.

## 6. Verificação no cluster

- [x] 6.1 Com autorização do operador:
  - criar um cluster kind descartável (`aidb-otel`, configuração própria no scratchpad, a partir de `deploy/pilot-k8s/kind-cluster.yaml` com outro nome e outra porta);
  - carregar a imagem do portal;
  - confirmar, de um Pod, que `172.30.0.6:8200` responde.

  Verificar com o JSON do APM Server lido de dentro do cluster.
- [x] 6.2 Instalar o chart com `observability.enabled=true`, `exporter.endpoint=172.30.0.6:8200`, `exporter.insecure=true`, `environment=teste-k8s`, tracing do Traefik ligado e `kubeletstats` ligado (com `insecureSkipVerify` no kind). Abrir o portal e rodar uma execução com o harness fake num sistema descartável. Verificar no Elasticsearch de teste:
  - o portal chega com `service.version` igual à tag e `k8s.pod.name` preenchido;
  - um traço tem o span do Traefik como pai da transação do portal, sem a query string;
  - as métricas de CPU e memória do Pod do sistema chegam com o slug do sistema como `service.name`;
  - nenhum documento vem de Pods de outros namespaces.
- [x] 6.3 Desligar `observability.enabled` com `helm upgrade` e verificar que os recursos do Collector somem e o portal sobe sem variáveis OTEL. Depois, apagar o cluster `aidb-otel`. Opcional, se o operador ligar o `secret_token` no APM Server de teste: repetir 6.2 com um Secret de token e verificar que os dados chegam, e que sem o Secret o APM Server recusa.

- Resultado da verificação (cluster `aidb-otel`, já apagado):
  - De dentro do cluster, um Pod alcança o APM Server de teste.
  - O portal chega com `service.version=1.8.0`, ambiente `teste-k8s` e `kubernetes.pod.name`.
  - O traço tem a transação do Traefik → `ReverseProxy` → a transação do portal. A query string fica com os valores mascarados (`token=REDACTED`).
  - Métricas do `kubeletstats`: o Pod do sistema sai com `service.name=otel-k8s`, o slug e o id, e só do namespace `aidb`.
  - Desligar recusa enquanto o Traefik ainda manda ao Collector. Com tudo desligado, os recursos e as variáveis somem.
  - Achado: o `kubeletstats` 0.112 marca `*.cpu.utilization` como obsoleta. O agente passou a usar o feature gate `receiver.kubeletstats.enableCPUUsageMetrics`, e `k8s.pod.cpu.usage` chegou.
  - A parte opcional do token não foi feita: o APM Server de teste não tem `secret_token`. O cabeçalho montado tem cobertura nos testes do chart.
  - As imagens multiplataforma do Collector e do Postgres não carregam por `kind load` neste Docker (containerd snapshotter); o nó baixou do registro.

## Workflow follow-up

- Arquivar a change (sincronizando `service-observability`) na mesma branch, antes de abrir a PR. Depois, PR, merge e release.
- Próxima change: borda das apps, com `/apps/<slug>` como serviço próprio no APM, alinhado ao `service.name` por slug do `kubeletstats`.
