# 0026 — Métricas de recursos por container via cAdvisor, rotuladas no scrape

* Status: aceito
* Data: 2026-11-09
* Decidida em: change `container-resource-metrics` (etapa 6 do roadmap de confinamento,
  endereçando o "Não resolve ainda" deixado por ela)
* Relacionada: [ADR 0025](0025-telemetria-otel-agnostica-de-backend.md) (Prometheus já subia
  decorativo no profile `observability`; esta ADR é quem finalmente o instrumenta)

## Contexto

A etapa 6 deixou o Prometheus decorativo: ele subia no profile `observability`, mas nenhuma
métrica real de uso de recursos por sistema (CPU, memória, processos) era coletada ou exposta.
Explorando o que fazer com ele, o operador levantou uma restrição que moldou a decisão: hoje o
deploy é Docker, mas uma migração futura para Kubernetes é esperada, e a estrutura de coleta não
deveria precisar ser refeita nessa migração.

## Decisão

**cAdvisor como coletor, em profile próprio (`metrics`), não dentro de `observability`.** cAdvisor
lê direto da API do Docker/containerd — não precisa de nenhuma instrumentação no código do portal
ou do broker. Fica em profile separado porque rastreamento de execução (Tempo/Loki) e uso de
recursos são preocupações independentes: uma pessoa pode querer só uma delas.

**Grafana passa a ser compartilhado entre os profiles `observability` e `metrics`**, sem
`depends_on` fixo em `prometheus`/`tempo`/`loki` — verificado ao vivo que ele sobe saudável com
qualquer um dos dois profiles isolado, e que subir os dois juntos resulta em uma única instância,
não duas.

**Labels do Docker são renomeados para nomes genéricos no scrape do Prometheus
(`metric_relabel_configs`), nunca consultados pelo nome bruto
(`container_label_appaiforge_slug`) no dashboard.** Isso isola a dependência de plataforma na
configuração do Prometheus: migrar para Kubernetes significa trocar `static_configs` por
`kubernetes_sd_configs` ali, sem o dashboard do Grafana precisar mudar — cAdvisor já vem embutido
no kubelet, exposto em `/metrics/cadvisor`, então o mesmo PromQL funciona nos dois mundos.

**Disco ficou fora do escopo**, por decisão explícita do operador após avaliar a portabilidade:
`container_fs_*` (cAdvisor/Docker) não mapeia de forma limpa para `kubelet_volume_stats_*`
(Kubernetes) — ao contrário de CPU/memória/pids, que têm equivalente direto nos dois mundos. CPU,
memória e pids ficaram no escopo final.

**Limite de pids vem de uma variável do dashboard (`$pids_limit`), não de uma métrica.** Achado ao
vivo: cAdvisor expõe `container_spec_cpu_quota`/`container_spec_memory_limit_bytes` (permitindo
calcular % de CPU/memória dinamicamente), mas não expõe limite de pids nenhum. Sem equivalente de
métrica, a variável textual (default 512) precisa ser mantida em sincronia manual com
`APPAIFORGE_CONTAINER_PIDS_LIMIT` se o deploy mudar o padrão — documentado na própria variável.

## Alternativas consideradas

- **Instrumentar o portal para expor métricas próprias de uso de recursos dos sistemas** —
  descartada: exigiria o portal consultar a API do Docker/containerd ele mesmo e expor um
  endpoint `/metrics`, duplicando o que o cAdvisor já faz de forma madura e sem tocar no código da
  aplicação.
- **cAdvisor dentro do profile `observability` (junto com Tempo/Loki)** — descartada: acopla duas
  preocupações independentes (rastreamento de execução vs. uso de recursos); alguém que só quer
  uma delas seria forçado a subir a outra.
- **Dashboard consultando os labels brutos do Docker diretamente (`container_label_appaiforge_*`)**
  — descartada: a migração futura para Kubernetes (achado trazido pelo operador) traria nomes de
  label completamente diferentes, obrigando a reescrever o dashboard; isolar isso em
  `metric_relabel_configs` no Prometheus mantém o dashboard estável.
- **Incluir métricas de disco no escopo** — descartada após avaliar portabilidade: é a única das
  quatro métricas sem equivalente direto em Kubernetes, então ficaria para reavaliar se/quando a
  migração acontecer.

## Consequências

- Migrar de Docker para Kubernetes, quando acontecer, deve ser uma troca isolada em
  `prometheus.yml` (`static_configs` → `kubernetes_sd_configs`), sem exigir mudança no dashboard —
  não verificado ao vivo nesta change (não há cluster Kubernetes disponível), apenas pelo desenho
  do scrape.
- Dois achados de infraestrutura corrigidos ao vivo durante a implementação, nenhum coberto pelos
  testes unitários (a change não toca código Python):
  1. `cAdvisor v0.49.1` não reconhece o storage backend containerd-snapshotter deste Docker
     29.9.3 — toda coleta de métricas de container falhava silenciosamente. Corrigido subindo
     para `v0.55.1`.
  2. `relabel_configs` não se aplica a labels do corpo já raspado da métrica (como os labels do
     Docker que o cAdvisor expõe) — só atua na descoberta do alvo, antes do scrape. A renomeação
     correta usa `metric_relabel_configs`.
- O limite de pids no dashboard é uma variável textual com valor hardcoded (default 512), não uma
  métrica — ponto de desvio manual se `APPAIFORGE_CONTAINER_PIDS_LIMIT` mudar e a variável não for
  atualizada junto.
- Disco permanece sem visibilidade de uso por sistema — aceito como lacuna conhecida, não resolvida
  por esta change.
