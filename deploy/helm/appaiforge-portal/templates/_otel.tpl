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
      processors: [memory_limiter, batch]
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
