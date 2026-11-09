# Proposal

## Why

Cada container de sistema roda com limites de CPU, memória e quantidade de processos já aplicados (`container_cpus`, `container_mem_mb`, `container_pids_limit` em `config.py`), mas não existe nenhuma visibilidade de uso real contra esses limites — não dá pra saber se um sistema está perto de ser OOM-killed ou de estourar o teto de processos antes de acontecer. O profile `observability` já sobe um Prometheus, mas ele é hoje puramente decorativo (só faz scrape de si mesmo).

## What Changes

- Novo profile `metrics` no `deploy/docker-compose.yml`, com cAdvisor fazendo scrape dos cgroups dos containers de sistema (sem nenhum código novo no portal — lê direto do Docker) e um Prometheus próprio consumindo essas métricas.
- O serviço Grafana sai de dentro do profile `observability` e passa a ser compartilhado: sobe junto de `observability`, de `metrics`, ou dos dois, nunca duplicado.
- Um dashboard provisionado no Grafana, templado por sistema (variável ligada ao label `appaiforge.slug` que os containers já carregam), mostrando CPU, memória e quantidade de processos como percentual do limite configurado daquele sistema.
- Escopo deliberadamente **não inclui disco**: é a métrica que menos sobrevive a uma futura migração para Kubernetes (troca de família de métrica no kubelet), decisão tomada em conversa com o operador.
- As queries do dashboard usam nomes de label genéricos (`slug`, `system_id`), normalizados por regra de *relabeling* no `prometheus.yml` — preparação deliberada para a etapa 8 do roadmap (Kubernetes), onde o cAdvisor standalone é substituído pelo cAdvisor já embutido no kubelet sem precisar reescrever o dashboard.

## Capabilities

### New Capabilities
- `container-resource-metrics`: visibilidade de uso de CPU, memória e processos de cada container de sistema, contra os limites configurados, via dashboard Grafana.

### Modified Capabilities
(nenhuma — os limites em si, definidos pela capability `container-lifecycle`, não mudam de comportamento; esta change só adiciona observabilidade sobre eles)

## Impact

- **Infra**: `deploy/docker-compose.yml` (novo profile `metrics` com cAdvisor + Prometheus; Grafana sai de `observability` e passa a ativar com qualquer um dos dois profiles), novos arquivos de config em `deploy/observability/` (config do Prometheus do profile `metrics`, provisionamento do dashboard e do datasource Prometheus no Grafana, regra de relabeling dos labels do container).
- **Código**: nenhum — esta change não toca em `portal/appaiforge/`.
