# Proposal

## Why

Etapa 8 do roadmap de confinamento (`docs/roadmap-confinamento-do-agente.md`) pede um segundo
driver de provisionamento (Kubernetes) ao lado do driver Docker atual, para validar que a
arquitetura de confinamento (etapas 1–7) não está amarrada a um orquestrador específico — mesmo
critério de "teste da arquitetura" já usado com sucesso na etapa 7 (segundo agente). Hoje
`provisioning.py` fala direto com o SDK do Docker, sem nenhuma fronteira de driver; qualquer
caminho a Kubernetes (gerenciado ou local) exige essa fronteira existir primeiro. O alvo imediato
de validação é um cluster `kind` local.

## What Changes

- Introduz uma interface de driver de provisionamento (`ProvisioningDriver` ou equivalente) com
  duas implementações: a existente (Docker, comportamento inalterado) e uma nova (Kubernetes),
  selecionável por configuração do portal.
- Driver Kubernetes cria, por sistema, um Pod com três containers (agente + sidecar `dbgate` +
  sidecar `httpsproxy`), compartilhando o network namespace do Pod — equivalente ao
  `network_mode: container:<id>` de hoje, sem a dependência de ordem de criação que isso exige no
  Docker.
- Workspace e config de cada sistema passam a ser **PVC + StorageClass** no driver Kubernetes
  (hoje bind mount de `/opt/appaiforge/workspaces|configs` no driver Docker) — portável para
  qualquer cluster real, usando o `local-path-provisioner` que o `kind` já traz por padrão.
- Roteamento de `/apps/{slug}` passa a usar Traefik **dentro do cluster** (Ingress ou Gateway API)
  quando o driver Kubernetes está ativo, substituindo o file provider externo que resolve pelo DNS
  do bridge Docker; `kind` expõe as portas do Ingress ao host via `extraPortMappings`.
- Limites de recursos (CPU, memória, disco) mapeados para `resources.limits` do Pod. **Limitação
  aceita e documentada**: `pids_limit` (hoje um hard limit de cgroup por container) não tem
  equivalente de 1ª classe por container no Kubernetes — o driver Kubernetes não impõe o mesmo
  limite de processos que o driver Docker impõe hoje.
- Reconciliação do driver Kubernetes usa polling contra a API (não watch/informers) nesta etapa.
- Primeiro incremento de validação: um cluster `kind` local, com manifesto de cluster (config do
  `kind` com `extraPortMappings`) incluído no change.
- Landlock/seccomp (`afsupervisor/sandbox.py`) **não muda** — é aplicado em processo, dentro do
  container, agnóstico de orquestrador.

## Capabilities

### New Capabilities
- `container-driver-kubernetes`: define o comportamento do driver de provisionamento Kubernetes —
  Pod por sistema com os três containers, PVC para workspace/config, roteamento via Ingress/Gateway
  dentro do cluster, mapeamento de limites de recursos e a limitação conhecida de `pids_limit`.

### Modified Capabilities
- `container-lifecycle`: generaliza "um container por sistema" para admitir mais de um driver de
  provisionamento selecionável por configuração (Docker ou Kubernetes), e relaxa "limites de
  recursos padrão" para refletir que o limite de quantidade de processos é melhor-esforço, não
  garantido, sob o driver Kubernetes.

## Impact

- **Código**: `portal/appaiforge/provisioning.py` (extração de uma interface de driver a partir do
  código hoje monolítico e Docker-específico), `portal/appaiforge/edge.py` (roteamento
  condicionado ao driver ativo), configuração do portal (seleção de driver).
- **Infra nova**: manifestos Kubernetes (Pod/PVC/StorageClass/Ingress ou Gateway por sistema),
  configuração de cluster `kind` para o ambiente de teste local.
- **Sem mudança**: `base-image/afsupervisor/sandbox.py` (Landlock/seccomp), `base-image/dbproxy/`,
  `base-image/httpproxy/` (sidecars rodam como containers do mesmo Pod, sem mudança de código
  próprio) — consistente com o critério de sucesso negativo já usado na etapa 7.
- **Dependências novas**: cluster `kind` + `kubectl` no ambiente de desenvolvimento/CI que for
  validar este driver.
