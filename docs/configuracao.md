# Configuração (env `APPAIFORGE_*`)

← [README](../README.md)

| Variável | Padrão | O quê |
|---|---|---|
| `DATABASE_URL` | postgres do compose | metadados do portal |
| `SECRET_KEY` | — | **obrigatória em produção** (deriva a cifra de segredos) |
| `PROVISIONING_DRIVER` | `docker` | `kubernetes` materializa cada sistema como Pod — ver [driver Kubernetes](driver-kubernetes.md) |
| `HARNESS_MODE` | `opencode` (no compose: `fake`) | `fake` = agente determinístico sem LLM (dev/E2E) |
| `FAKE_DELAY` | `0.15` | ritmo do harness fake em segundos |
| `BASE_IMAGE` | `appaiforge/base:0.1.0` | imagem dos containers de sistema |
| `CONTAINER_CPUS` / `CONTAINER_MEM_MB` / `CONTAINER_DISK_GB` | 2 / 2048 / 10 | limites por sistema (ADR 0013) |
| `CONTAINER_PIDS_LIMIT` | 512 | teto de processos por container (ADR 0018) |
| `MAX_SYSTEMS` | 10 | teto de sistemas simultâneos |
| `HEALTH_INTERVAL` | 15 | sonda de saúde das apps (segundos) |
| `WORKSPACES_DIR` / `HOST_WORKSPACES_DIR` | /workspaces | raiz dos workspaces (bind compartilhado) |
| `DYNAMIC_CONFIG_DIR` | /dynamic | rotas dinâmicas do Traefik (volume compartilhado) |
| `CONFIGS_DIR` / `HOST_CONFIG_DIR` | /configs | config do agente (MCP, provedor, chaves) **fora do workspace**, montada read-only no container do sistema |
| `DISPLAY_TIMEZONE` | America/Sao_Paulo | fuso das datas exibidas (gravadas em UTC) |
| `INFERENCE_BROKER_ENABLED` | `false` | broker de inferência: token opaco no container + LiteLLM (ADR 0020, ver [LLM e broker](llm-e-broker.md)) |
| `LITELLM_API_KEY` / `INFERENCE_BROKER_SERVICE_TOKEN` | — | master key do LiteLLM e segredo portal↔broker (obrigatórias com o broker ligado) |
| `DB_GATE_MODE` | `enforce` | `enforce` o sidecar recusa bloqueada/confirmável na hora, sem aprovação (ADR 0021/0023); `shadow` audita sem bloquear — ver [Segurança](seguranca.md) |
| `DB_GATE_PROXY_SERVICE_TOKEN` | — | segredo compartilhado entre o sidecar e o portal (mesmo padrão do broker) |
| `SEED_DEMO_ADMIN` | — | `1` semeia o admin de dev quando não há usuários (nunca em produção) |

Limites: CPU/memória aplicados via Docker; **quota de disco** requer storage driver com suporte a `storage-opt` (overlay2/ext4 não suporta — o container sobe sem quota e o portal registra a ressalva).
