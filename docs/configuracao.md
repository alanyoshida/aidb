# Configuração (env `APPAIFORGE_*`)

← [README](../README.md)

| Variável | Padrão | O quê |
|---|---|---|
| `DATABASE_URL` | postgres do compose | metadados do portal |
| `SECRET_KEY` | — | **obrigatória em produção** (deriva a cifra de segredos) |
| `PROVISIONING_DRIVER` | `docker` | `kubernetes` materializa cada sistema como Pod — ver [driver Kubernetes](driver-kubernetes.md) |
| `HARNESS_MODE` | `opencode` (no compose: `fake`) | `fake` = agente determinístico sem LLM (dev/E2E) |
| `FAKE_DELAY` | `0.15` | ritmo do harness fake em segundos |
| `BASE_IMAGE` | `appaiforge/base:1.12.0` | imagem dos containers de sistema e dos sidecars (no chart, `portal.baseImage`) |
| `CLAUDE_CODE_IMAGE` | `appaiforge/claude-code:1.12.0` | imagem dos sistemas com o perfil de agente `claude-code` (no chart, `portal.claudeCodeImage`) |
| `K8S_IMAGE_PULL_SECRETS` | — | driver Kubernetes: Secrets de pull dos Pods de sistema, separados por vírgula (no chart, `portal.systemImagePullSecrets`). Trocar este valor, `BASE_IMAGE` ou `CLAUDE_CODE_IMAGE` faz a reconciliação recriar os Pods que ainda usam o valor anterior, o que interrompe uma execução do agente em andamento |
| `CONTAINER_CPUS` / `CONTAINER_MEM_MB` / `CONTAINER_DISK_GB` | 2 / 2048 / 10 | limites por sistema (ADR 0013) |
| `CONTAINER_PIDS_LIMIT` | 512 | teto de processos por container (ADR 0018) |
| `MAX_SYSTEMS` | 10 | teto de sistemas simultâneos |
| `INSTALLATION_ROLE` | `development` | papel do portal: `development` aceita sistemas com agente e só implantação; `production` só aceita sistemas só implantação — nenhum agente é criado nem provisionado (ver [Sistema só implantação](guia-de-uso.md#sistema-só-implantação)) |
| `ALLOW_SHARED_DOCKER_HOST` | `false` | **só para testes**: deixa um portal de produção com driver Docker subir num host que tem containers de outra instalação, só registrando aviso. Sem ela, o portal de produção recusa subir e lista esses containers: produção precisa de host Docker próprio |
| `DEPLOY_HEALTH_TIMEOUT` | 90 | prazo, em segundos, para a app de uma versão recém-implantada responder em três checagens seguidas; senão volta à anterior |
| `DEPLOY_HEALTH_INTERVAL` | 2 | intervalo, em segundos, entre essas checagens |
| `DEPLOY_POLL_INTERVAL` | 60 | intervalo, em segundos, da consulta periódica de tags novas dos sistemas só implantação em modo automático |
| `WEBHOOK_BASE_URL` | — | endereço do portal visto pelo GitLab, mostrado na aba Implantação para o webhook; vazio = `PUBLIC_BASE_URL` |
| `PORTAL_INTERNAL_URL` | `http://portal:8080` | endereço do portal na rede dos containers: rota raiz do Traefik, forwardAuth das apps e chamadas dos sidecars; mude quando o serviço do portal tiver outro nome. O chart Helm passa o nome completo do Service (`<nome>.<namespace>.svc.cluster.local`), porque o Traefik chama o forwardAuth de outro namespace |
| `HEALTH_INTERVAL` | 15 | sonda de saúde das apps (segundos) |
| `RECONCILE_INTERVAL` | 300 | intervalo, em segundos, da reconciliação periódica dos containers ou Pods de sistema com o estado registrado: recria a unidade ausente ou divergente, republica a rota, checa a saúde das conexões e, num portal de produção, remove sistemas com agente. Uma passada sempre roda logo depois da subida, em segundo plano; `0` desliga só a periódica. No chart, via `portal.extraEnv` |
| `WORKSPACES_DIR` / `HOST_WORKSPACES_DIR` | /workspaces | raiz dos workspaces (bind compartilhado) |
| `DYNAMIC_CONFIG_DIR` | /dynamic | rotas dinâmicas do Traefik (volume compartilhado) |
| `CONFIGS_DIR` / `HOST_CONFIG_DIR` | /configs | config do agente (MCP, provedor, chaves) **fora do workspace**, montada read-only no container do sistema |
| `DISPLAY_TIMEZONE` | America/Sao_Paulo | fuso das datas exibidas (gravadas em UTC) |
| `INFERENCE_BROKER_ENABLED` | `false` | broker de inferência: token opaco no container + LiteLLM (ADR 0020, ver [LLM e broker](llm-e-broker.md)) |
| `LITELLM_API_KEY` / `INFERENCE_BROKER_SERVICE_TOKEN` | — | master key do LiteLLM e segredo portal↔broker (obrigatórias com o broker ligado) |
| `DB_GATE_MODE` | `enforce` | `enforce` o sidecar recusa bloqueada/confirmável na hora, sem aprovação (ADR 0021/0023); `shadow` audita sem bloquear — ver [Segurança](seguranca.md) |
| `DB_GATE_PROXY_SERVICE_TOKEN` | — | segredo compartilhado entre o sidecar e o portal (mesmo padrão do broker) |
| `SEED_DEMO_ADMIN` | — | `1` semeia o admin de dev quando não há usuários (nunca em produção) |
| `AUTH_MODE` | `local` | `local` (e-mail/senha) ou `oidc` (SSO); gravado no primeiro boot, não muda depois — ver [Autenticação](autenticacao.md) |
| `PUBLIC_BASE_URL` | — | URL pública do portal (obrigatória no modo `oidc`; base do `redirect_uri`) |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | — | IdP e client confidencial (obrigatórios no modo `oidc`) |
| `OIDC_INTERNAL_BASE_URL` | — | base interna do IdP para discovery/token/JWKS |
| `OIDC_SCOPES` / `OIDC_ROLES_CLAIM` / `OIDC_GROUPS_CLAIM` | `openid email profile` / `realm_access.roles` / `groups` | escopos e claims de papel e grupos |
| `OIDC_REVALIDATE_SECONDS` / `OIDC_NETWORK_GRACE_SECONDS` | 300 / 60 | revalidação da sessão no IdP e tolerância a IdP fora do ar |
| `BREAKGLASS_EMAIL` / `BREAKGLASS_PASSWORD_HASH` | — | admin de emergência (hash de `appaiforge hash-password`) |
| `BREAKGLASS_SESSION_HOURS` | 8 | duração máxima da sessão do break-glass |
| `LOGIN_RATE_LIMIT_ATTEMPTS` / `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | 5 / 900 | falhas por IP+e-mail que bloqueiam o login local, e a janela |
| `IDENTITY_TOKEN_TTL_SECONDS` | 60 | validade do JWT de identidade entregue às apps |
| `OTEL_TRACES_ENDPOINT` | — | URL OTLP/HTTP de traços do Collector (ex.: `http://otel-collector:4318/v1/traces`); vazio = nada é exportado. Aponta sempre para um Collector, nunca para um backend ([ADR 0025](adr/0025-telemetria-otel-agnostica-de-backend.md)) |
| `OTEL_LOGS_ENDPOINT` | — | URL OTLP/HTTP de logs do Collector (`.../v1/logs`); vazio = logs só no processo |
| `OTEL_METRICS_ENDPOINT` | — | URL OTLP/HTTP de métricas do Collector (`.../v1/metrics`): duração de requisições HTTP, pool do banco do portal, CPU e memória do processo; vazio = nenhuma métrica ([ADR 0033](adr/0033-auto-instrumentacao-do-portal-e-elastic-apm.md)) |
| `OTEL_SPAN_RETENTION_DAYS` | 30 | retenção dos spans guardados em Postgres para o Debug log do chat |

Fora do prefixo `APPAIFORGE_`, portal e broker aceitam a variável padrão do OpenTelemetry `OTEL_RESOURCE_ATTRIBUTES` (ex.: `deployment.environment=producao,service.version=1.8.0`): ela prevalece sobre o nome, a versão e a instância que o código põe na telemetria ([ADR 0033](adr/0033-auto-instrumentacao-do-portal-e-elastic-apm.md)).

Limites: CPU/memória aplicados via Docker; **quota de disco** requer storage driver com suporte a `storage-opt` (overlay2/ext4 não suporta — o container sobe sem quota e o portal registra a ressalva).
