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
