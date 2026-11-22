{{/*
Configuração gerada do Collector central (change chart-observability-otel, D6): OTLP de entrada,
memory_limiter e batch em todos os sinais, cumulativetodelta nas métricas quando o destino pede
delta (APM Server) e um exporter OTLP gRPC para o destino. O cabeçalho de autorização e a CA só
entram quando o Secret do destino fornece essas chaves (D2).
*/}}
{{- define "appaiforge-portal.collectorConfig" -}}
{{- $o := .o -}}
extensions:
  health_check:
    endpoint: 0.0.0.0:13133
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20
  batch: {}
  {{- if $o.exporter.deltaMetrics }}
  cumulativetodelta: {}
  {{- end }}
  # Borda das apps (change edge-app-tracing, ADR 0035). O mesmo bloco está nos três Collectors
  # (perfil Elastic, perfil Grafana e chart) e um teste confere que são iguais. Só toca spans do
  # Traefik (resource service.name == "traefik"): descarta assets e websocket do NiceGUI, tira a
  # query string, dá a cada pedido a /apps/<slug> o nome "<método> <caminho na app com {id}>" e
  # move esses spans para um serviço com o nome do slug, o mesmo do kubeletstats.
  filter/edge:
    error_mode: ignore
    traces:
      span:
        - 'resource.attributes["service.name"] == "traefik" and attributes["url.path"] != nil and IsMatch(attributes["url.path"], "/_nicegui")'
        - 'resource.attributes["service.name"] == "traefik" and attributes["url.original"] != nil and IsMatch(attributes["url.original"], "/_nicegui")'
        - 'resource.attributes["service.name"] == "traefik" and attributes["url.full"] != nil and IsMatch(attributes["url.full"], "/_nicegui")'
  transform/edge:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - delete_key(attributes, "url.query") where resource.attributes["service.name"] == "traefik"
          - replace_pattern(attributes["url.full"], "[?].*", "") where resource.attributes["service.name"] == "traefik" and attributes["url.full"] != nil
          - replace_pattern(attributes["url.original"], "[?].*", "") where resource.attributes["service.name"] == "traefik" and attributes["url.original"] != nil
          - replace_pattern(attributes["http.target"], "[?].*", "") where resource.attributes["service.name"] == "traefik" and attributes["http.target"] != nil
          - replace_pattern(attributes["http.url"], "[?].*", "") where resource.attributes["service.name"] == "traefik" and attributes["http.url"] != nil
          - set(attributes["appaiforge.slug"], attributes["url.path"]) where resource.attributes["service.name"] == "traefik" and attributes["url.path"] != nil and IsMatch(attributes["url.path"], "^/apps/[a-z0-9-]+(/|$)")
          - replace_pattern(attributes["appaiforge.slug"], "^/apps/([a-z0-9-]+).*", "$$1") where attributes["appaiforge.slug"] != nil
          - set(attributes["appaiforge.route"], attributes["url.path"]) where attributes["appaiforge.slug"] != nil
          - replace_pattern(attributes["appaiforge.route"], "^/apps/[a-z0-9-]+", "") where attributes["appaiforge.route"] != nil
          - set(attributes["appaiforge.route"], "/") where attributes["appaiforge.route"] == ""
          - replace_pattern(attributes["appaiforge.route"], "/[0-9]+(/|$)", "/{id}$$1") where attributes["appaiforge.route"] != nil
          - replace_pattern(attributes["appaiforge.route"], "/[0-9a-fA-F-]{16,}(/|$)", "/{id}$$1") where attributes["appaiforge.route"] != nil
          - set(name, Concat([attributes["http.request.method"], attributes["appaiforge.route"]], " ")) where attributes["appaiforge.route"] != nil and attributes["http.request.method"] != nil
          - set(name, Concat([attributes["http.method"], attributes["appaiforge.route"]], " ")) where attributes["appaiforge.route"] != nil and attributes["http.request.method"] == nil and attributes["http.method"] != nil
          - delete_key(attributes, "appaiforge.route")
  groupbyattrs/edge:
    keys: [appaiforge.slug]
  transform/edge-service:
    error_mode: ignore
    trace_statements:
      - context: resource
        statements:
          - set(attributes["service.name"], attributes["appaiforge.slug"]) where attributes["appaiforge.slug"] != nil
exporters:
  otlp:
    endpoint: {{ $o.exporter.endpoint | quote }}
    tls:
      insecure: {{ $o.exporter.insecure }}
      {{- if .useCA }}
      ca_file: /etc/otel-exporter/ca.crt
      {{- end }}
    {{- if .useToken }}
    headers:
      Authorization: ${env:EXPORTER_AUTHORIZATION}
    {{- end }}
service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, filter/edge, transform/edge, groupbyattrs/edge, transform/edge-service, batch]
      exporters: [otlp]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter{{ if $o.exporter.deltaMetrics }}, cumulativetodelta{{ end }}, batch]
      exporters: [otlp]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
{{- end -}}

{{/*
Configuração do agente de kubeletstats (D5): estatísticas do kubelet do próprio nó, só dos
namespaces da instalação, marcadas com o sistema dono do Pod, para o Collector central.
*/}}
{{- define "appaiforge-portal.agentConfig" -}}
{{- $k := .Values.observability.kubeletstats -}}
{{- $namespaces := uniq (list .Release.Namespace (include "appaiforge-portal.systemsNamespace" .)) -}}
extensions:
  health_check:
    endpoint: 0.0.0.0:13133
receivers:
  kubeletstats:
    collection_interval: {{ $k.collectionInterval }}
    auth_type: serviceAccount
    endpoint: https://${env:K8S_NODE_IP}:10250
    insecure_skip_verify: {{ $k.insecureSkipVerify }}
    metric_groups: [pod, container]
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20
  # só os namespaces da instalação: o kubelet do nó mostra Pods de todo o cluster
  filter/namespaces:
    error_mode: ignore
    metrics:
      metric:
        - 'not ({{- range $i, $ns := $namespaces }}{{ if $i }} or {{ end }}resource.attributes["k8s.namespace.name"] == "{{ $ns }}"{{ end -}})'
  {{- range $i, $ns := $namespaces }}
  # um por namespace: cada um só observa os Pods do seu (Role no namespace, sem ClusterRole de pods)
  k8sattributes/{{ $i }}:
    auth_type: serviceAccount
    passthrough: false
    filter:
      namespace: {{ $ns | quote }}
    extract:
      metadata: [k8s.pod.name, k8s.pod.uid]
      labels:
        - tag_name: appaiforge.slug
          key: appaiforge.slug
          from: pod
        - tag_name: appaiforge.system_id
          key: appaiforge.system_id
          from: pod
        - tag_name: app.kubernetes.io/component
          key: app.kubernetes.io/component
          from: pod
    pod_association:
      - sources:
          - from: resource_attribute
            name: k8s.pod.uid
  {{- end }}
  # service.name: o slug no Pod de um sistema (a borda das apps usará o mesmo nome),
  # appaiforge-portal no Pod do portal e appaiforge-k8s no resto da instalação
  transform/service:
    error_mode: ignore
    metric_statements:
      - context: resource
        statements:
          - set(attributes["service.name"], attributes["appaiforge.slug"]) where attributes["appaiforge.slug"] != nil
          - set(attributes["service.name"], "appaiforge-portal") where attributes["service.name"] == nil and attributes["app.kubernetes.io/component"] == "portal"
          - set(attributes["service.name"], "appaiforge-k8s") where attributes["service.name"] == nil
  batch: {}
exporters:
  otlphttp:
    endpoint: {{ include "appaiforge-portal.otlpBase" . | quote }}
service:
  extensions: [health_check]
  pipelines:
    metrics:
      receivers: [kubeletstats]
      processors: [memory_limiter, filter/namespaces{{ range $i, $ns := $namespaces }}, k8sattributes/{{ $i }}{{ end }}, transform/service, batch]
      exporters: [otlphttp]
{{- end -}}
