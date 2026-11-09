# Design

## Context

Ver proposal.md - Why. Containers de sistema já carregam os labels `appaiforge.system_id`/`appaiforge.slug` ([provisioning.py:481-483](../../../portal/appaiforge/provisioning.py)), usados hoje para reconciliação. O profile `observability` já sobe um `prometheus` ([docker-compose.yml](../../../deploy/docker-compose.yml)), mas ele nunca teve nada real para fazer scrape além de si mesmo - está decorativo desde a etapa 6. O Grafana já é provisionado com um datasource Prometheus apontando para esse serviço ([datasources.yaml](../../../deploy/observability/grafana/provisioning/datasources/datasources.yaml)).

O host de dev roda cgroup v2 (confirmado no roadmap de confinamento, etapa 9).

## Goals / Non-Goals

**Goals:**
- Visibilidade de CPU, memória e pids por sistema, sem nenhuma instrumentação no código do portal.
- `metrics` como profile independente de `observability` - liga um sem o outro.
- Grafana nunca duplicado, disponível com qualquer um dos dois profiles.
- As queries do dashboard sobrevivem à troca de mecanismo de coleta na migração para Kubernetes (etapa 8 do roadmap) sem precisar ser reescritas.

**Non-Goals:**
- Disco não entra no dashboard (decisão do operador: é a métrica que menos sobrevive à migração para Kubernetes, por trocar de família de métrica no kubelet).
- Não adiciona alerta/threshold automático (ex.: notificar quando um sistema passa de 80% do limite) - fica para uma iteração futura, se necessário.
- Não altera os limites em si (`container_cpus`/`container_mem_mb`/`container_pids_limit`) nem o comportamento de `container-lifecycle` - esta change só observa.
- Não resolve a migração para Kubernetes em si (etapa 8) - só evita que esta change precise ser refeita quando ela acontecer.

## Decisions

### 1. cAdvisor como coletor, sem instrumentação no portal
cAdvisor lê diretamente os cgroups dos containers (mesma fonte de dado que `docker stats`), expondo métricas Prometheus padrão (`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, `container_processes` - entre outras, filtradas pelo Non-Goal de disco) já rotuladas com os labels Docker de cada container, incluindo `appaiforge.slug`/`appaiforge.system_id`. Nenhum código novo no portal.

Precisa de acesso somente-leitura ao cgroup e ao socket do Docker do host (`/sys/fs/cgroup:ro`, `/var/run/docker.sock:ro`, `/var/lib/docker:ro`, `/rootfs:ro` - montagens padrão da imagem oficial). Em cgroup v2, roda sem `--privileged`.

Alternativa considerada: `docker stats` consultado periodicamente pelo próprio portal e persistido - descartada; duplicaria o que o cAdvisor já faz de graça, com mais código para manter e sem o benefício de já ser uma métrica Prometheus padrão, portável ao kubelet.

### 2. `prometheus` migra do profile `observability` para `metrics`
O `prometheus` existente nunca teve relação real com Tempo/Loki (traces/logs não passam por ele) - ele estava em `observability` só porque foi criado junto na etapa 6, sem uso real. Como o scrape de métricas é seu único propósito de fato, ele migra para o profile `metrics`, ao lado do `cadvisor` novo. `observability` passa a ter só Tempo e Loki.

### 3. Grafana compartilhado via múltiplos profiles, sem `depends_on` rígido
`grafana` ganha `profiles: ["observability", "metrics"]` (Compose ativa o serviço se qualquer um dos profiles pedidos corresponder - comportamento já usado para os serviços do Collector nesta mesma change anterior). O `depends_on` de Grafana em `prometheus`/`tempo`/`loki` é removido: com profiles diferentes podendo estar de pé independentemente, um `depends_on` fixo nos três quebraria subir só um profile. Grafana sobe sempre; cada datasource aponta para seu hostname de sempre, e um datasource cujo serviço não está de pé naquele momento aparece como indisponível naquele painel específico - sem travar o Grafana nem os outros datasources, consistente com o requisito "Observabilidade de métricas opcional no deploy".

### 4. Labels normalizados no scrape, não na query
A regra de `relabel_configs` do job de scrape do cAdvisor em `prometheus.yml` renomeia `container_label_appaiforge_slug` → `slug` e `container_label_appaiforge_system_id` → `system_id`. O dashboard do Grafana usa só esses nomes genéricos, nunca o nome bruto do label Docker.

Isso isola a dependência de plataforma inteiramente no arquivo de scrape config: na migração para Kubernetes, o cAdvisor standalone some (substituído pelo cAdvisor já embutido no kubelet), e o scrape passa a usar `kubernetes_sd_configs` contra o endpoint do kubelet em vez de um alvo estático - mas a regra de relabel final ainda produz `slug`/`system_id` a partir do label do Pod (mesmo nome de label, se o Pod carregar `appaiforge.slug` como label do Kubernetes, não só como label Docker). O dashboard e suas queries PromQL não mudam uma linha.

Alternativa considerada: dashboard consultando `container_label_appaiforge_slug` diretamente - descartada; amarraria toda query à convenção de nome específica do cAdvisor-sobre-Docker, exigindo reescrever o dashboard inteiro na migração.

### 5. Dashboard templado por sistema, não um dashboard por sistema
Uma variável do Grafana (`$slug`, populada por `label_values(container_processes, slug)` ou equivalente) alimenta um único dashboard provisionado; trocar de sistema é trocar a variável, não abrir um dashboard diferente. Padrão usual do Grafana para "mesmo conjunto de painéis, por entidade" - evita gerar e manter N dashboards.

## Risks / Trade-offs

- [Risco] cAdvisor precisa de acesso de leitura a `/var/run/docker.sock` e ao filesystem do host (`/rootfs`, `/var/lib/docker`) - superfície maior que os demais serviços do profile `observability` → Mitigação: todas as montagens são `:ro`; cAdvisor é um projeto mantido pelo Google/Kubernetes SIG, usado como o próprio coletor de métricas do kubelet.
- [Risco] Painéis do Grafana referenciando um datasource cujo serviço não está de pé (ex.: só `metrics` ligado, sem `observability`) → Mitigação: comportamento esperado e aceito - painel individual mostra "sem dados"/erro de conexão, sem afetar os outros datasources nem travar o Grafana (mesmo requisito de "ausência não degrada" já estabelecido para a telemetria de execução).
- [Risco] Métricas de pids/memória podem ter nomes de métrica ligeiramente diferentes entre a versão standalone do cAdvisor e a embutida no kubelet → Mitigação: fora do escopo verificável agora (não há cluster Kubernetes); registrado aqui para quando a etapa 8 do roadmap acontecer de fato - o relabeling para `slug`/`system_id` já faz a parte que dá para preparar hoje.

## Migration Plan

1. `deploy/observability/prometheus.yml`: adiciona o job de scrape do cAdvisor com o `relabel_configs` para `slug`/`system_id`; `prometheus` sai do profile `observability` e entra em `metrics`.
2. `docker-compose.yml`: novo serviço `cadvisor` (profile `metrics`); `grafana` ganha `profiles: ["observability", "metrics"]` e perde o `depends_on` fixo.
3. `deploy/observability/grafana/provisioning/dashboards/`: novo arquivo de provisionamento do dashboard de recursos por sistema (painéis de CPU/memória/pids como % do limite, variável `$slug`).
4. Rollout: aditivo - nenhum serviço existente muda de comportamento; `observability` sozinho continua funcionando igual (só perde o Prometheus que nunca usava de verdade). Quem já tinha `observability` de pé e quer métricas agora soma `--profile metrics`.
5. Rollback: remover o profile `metrics`; `observability` volta a valer exatamente como funcionava antes desta change (Tempo + Loki + Grafana).
