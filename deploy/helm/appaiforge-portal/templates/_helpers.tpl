{{/*
Nome base do chart.
*/}}
{{- define "appaiforge-portal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Nome completo dos recursos. fullnameOverride vence tudo — é o que mantém
paridade 1:1 com os nomes fixos dos manifests antigos (appaiforge-portal,
appaiforge-portal-postgres) quando instalado com os defaults deste chart.
*/}}
{{- define "appaiforge-portal.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.postgres.fullname" -}}
{{- printf "%s-postgres" (include "appaiforge-portal.fullname" .) -}}
{{- end -}}

{{- define "appaiforge-portal.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "appaiforge-portal.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "appaiforge-portal.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Namespace onde o driver Kubernetes provisiona os Pods de sistema — mesmo
namespace da release quando portal.systemsNamespace não é definido (paridade
com os manifests antigos, que usavam sempre "appaiforge" para os dois).
*/}}
{{- define "appaiforge-portal.systemsNamespace" -}}
{{- default .Release.Namespace .Values.portal.systemsNamespace -}}
{{- end -}}

{{- define "appaiforge-portal.labels" -}}
app.kubernetes.io/name: {{ include "appaiforge-portal.name" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Modo de roteamento (change gateway-api-traefik-subchart, D0) e o Gateway das rotas no modo
gateway (D3): o deste chart quando o subchart do Traefik está ligado, senão `gateway.existing`.
*/}}
{{- define "appaiforge-portal.validateRouting" -}}
{{- if not (has .Values.routing.mode (list "ingressroute" "gateway")) -}}
{{- fail (printf "routing.mode deve ser ingressroute ou gateway (recebido: %s)" .Values.routing.mode) -}}
{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.gatewayMode" -}}
{{- if eq .Values.routing.mode "gateway" -}}true{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.createsGateway" -}}
{{- if and (eq .Values.routing.mode "gateway") .Values.traefik.enabled -}}true{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.gatewayName" -}}
{{- if .Values.traefik.enabled -}}
{{- include "appaiforge-portal.fullname" . -}}
{{- else -}}
{{- required "routing.mode=gateway com traefik.enabled=false exige gateway.existing.name e gateway.existing.namespace: informe o Gateway já existente no cluster que as rotas vão usar" .Values.gateway.existing.name -}}
{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.gatewayNamespace" -}}
{{- if .Values.traefik.enabled -}}
{{- .Release.Namespace -}}
{{- else -}}
{{- required "routing.mode=gateway com traefik.enabled=false exige gateway.existing.name e gateway.existing.namespace: informe o Gateway já existente no cluster que as rotas vão usar" .Values.gateway.existing.namespace -}}
{{- end -}}
{{- end -}}

{{/*
Guardas de produção (change add-production-portal-install, D4): um portal de produção não
semeia o admin de demonstração e lê os segredos de um Secret criado fora do Helm.
*/}}
{{- define "appaiforge-portal.validateProduction" -}}
{{- if not (has .Values.portal.installationRole (list "development" "production")) -}}
{{- fail (printf "portal.installationRole deve ser development ou production (recebido: %s)" .Values.portal.installationRole) -}}
{{- end -}}
{{- if eq .Values.portal.installationRole "production" -}}
{{- if .Values.portal.seedDemoAdmin -}}
{{- fail "portal.installationRole=production não pode semear o admin de demonstração: defina portal.seedDemoAdmin=false e use auth.breakglass ou OIDC para o primeiro admin" -}}
{{- end -}}
{{- if not .Values.secrets.existingSecret -}}
{{- fail "portal.installationRole=production exige secrets.existingSecret: crie o Secret fora do Helm (chaves secretKey, dbGateProxyServiceToken, postgresPassword) em vez de usar os valores de dev" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Namespaces cujas rotas o Gateway deste chart aceita: o da release (rota do portal) e o dos
sistemas (rotas que o driver cria), que podem ser o mesmo.
*/}}
{{- define "appaiforge-portal.gatewayAllowedNamespaces" -}}
from: Selector
selector:
  matchExpressions:
    - key: kubernetes.io/metadata.name
      operator: In
      values:
        {{- range uniq (list .Release.Namespace (include "appaiforge-portal.systemsNamespace" .)) }}
        - {{ . | quote }}
        {{- end }}
{{- end -}}

{{/*
Observabilidade (change chart-observability-otel, ADR 0034). Nome do Collector central e base
OTLP/HTTP que o portal e o agente usam: o Service do Collector deste chart, ou um Collector já
existente (collector.create=false).
*/}}
{{- define "appaiforge-portal.collectorName" -}}
{{- printf "%s-otel-collector" (include "appaiforge-portal.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "appaiforge-portal.agentName" -}}
{{- printf "%s-otel-agent" (include "appaiforge-portal.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "appaiforge-portal.otlpBase" -}}
{{- if .Values.observability.collector.create -}}
{{- printf "http://%s.%s.svc.cluster.local:4318" (include "appaiforge-portal.collectorName" .) .Release.Namespace -}}
{{- else -}}
{{- trimSuffix "/" .Values.observability.collector.endpoint -}}
{{- end -}}
{{- end -}}

{{/* Traefik do subchart com traços ou métricas OTLP ligados (true/vazio, por sinal). */}}
{{- define "appaiforge-portal.traefikOtlp" -}}
{{- $t := .Values.traefik | default dict -}}
{{- if $t.enabled -}}
{{- $o := dig .signal "otlp" dict $t -}}
{{- if and $o.enabled (dig "http" "enabled" false $o) -}}{{- dig "http" "endpoint" "" $o -}}{{- end -}}
{{- end -}}
{{- end -}}

{{- define "appaiforge-portal.validateObservability" -}}
{{- $o := .Values.observability -}}
{{- $collector := include "appaiforge-portal.collectorName" . -}}
{{- range $signal := list "tracing" "metrics" -}}
{{- $endpoint := include "appaiforge-portal.traefikOtlp" (dict "Values" $.Values "signal" $signal) -}}
{{- if $endpoint -}}
{{- if not $o.enabled -}}
{{- fail (printf "traefik.%s.otlp ligado exige observability.enabled=true: o Traefik manda para o Collector da observabilidade" $signal) -}}
{{- end -}}
{{- if and $o.collector.create (not (contains $collector $endpoint)) -}}
{{- fail (printf "traefik.%s.otlp.http.endpoint (%s) não aponta para o Collector desta instalação (%s): ajuste o endpoint, porque os valores do subchart não acompanham o fullnameOverride" $signal $endpoint $collector) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if $o.enabled -}}
{{- if $o.collector.create -}}
{{- if and (not $o.exporter.endpoint) (not $o.collector.config) -}}
{{- fail "observability.enabled=true exige o destino: informe observability.exporter.endpoint (ex.: apm.exemplo.com:8200) ou uma configuração própria em observability.collector.config" -}}
{{- end -}}
{{- else if not $o.collector.endpoint -}}
{{- fail "observability.collector.create=false exige observability.collector.endpoint: a base OTLP/HTTP do Collector que já existe no cluster" -}}
{{- end -}}
{{- if not (has $o.exporter.authScheme (list "Bearer" "ApiKey")) -}}
{{- fail (printf "observability.exporter.authScheme deve ser Bearer ou ApiKey (recebido: %s)" $o.exporter.authScheme) -}}
{{- end -}}
{{- if and $o.kubeletstats.enabled (not $o.collector.create) (not $o.collector.endpoint) -}}
{{- fail "observability.kubeletstats.enabled exige um Collector: o deste chart ou observability.collector.endpoint" -}}
{{- end -}}
{{- end -}}
{{- end -}}

