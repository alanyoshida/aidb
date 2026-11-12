# Design

## Context

Hoje `portal/appaiforge/provisioning.py` fala direto com o SDK do Docker, sem nenhuma fronteira
de driver: `provision_system` ([`provisioning.py:455`](../../../portal/appaiforge/provisioning.py))
cria o container principal via `client.containers.run()` ([:567](../../../portal/appaiforge/provisioning.py)),
depois os sidecars `dbgate` ([`_provision_dbgate_sidecar`, :600](../../../portal/appaiforge/provisioning.py))
e `httpsproxy` ([`_provision_httpsproxy_sidecar`, :641](../../../portal/appaiforge/provisioning.py)),
cada um com `network_mode=f"container:{system_container_id}"` ([:625](../../../portal/appaiforge/provisioning.py),
[:664](../../../portal/appaiforge/provisioning.py)) — por isso o container principal precisa existir
primeiro, só pra os sidecars descobrirem seu ID. Limites de recursos
(`nano_cpus`/`mem_limit`/`pids_limit`/`storage_opt`, [:537-541](../../../portal/appaiforge/provisioning.py))
e identidade de execução (`_execution_identity`, [:688](../../../portal/appaiforge/provisioning.py)) são
kwargs do SDK do Docker. `reconcile()` detecta drift via `docker.errors.NotFound`
([:93](../../../portal/appaiforge/provisioning.py), [:594](../../../portal/appaiforge/provisioning.py)).
Bind mounts de workspace/config vêm de `/opt/appaiforge/workspaces|configs/<slug>`. `edge.py` resolve
o endereço da app via DNS embutido do Docker (`appaiforge-sys-<slug>`) para o file provider do Traefik.

Landlock/seccomp (`base-image/afsupervisor/sandbox.py`) são aplicados via `preexec_fn` dentro do
processo do agente — não dependem do SDK do Docker nem do orquestrador, e não mudam nesta change.

Decisões de escopo já fechadas com o usuário (ver conversa de exploração): abstração de driver
completa (não um spike isolado), armazenamento via PVC + StorageClass (não hostPath), Traefik
dentro do cluster como Ingress/Gateway, e a lacuna de `pids_limit` aceita como limitação conhecida.

## Goals / Non-Goals

**Goals:**
- Uma interface de driver de provisionamento com duas implementações mantidas: Docker (existente,
  comportamento inalterado) e Kubernetes (nova).
- Driver Kubernetes validado ponta a ponta num cluster `kind` local: Pod por sistema com os três
  containers, PVC para workspace/config, roteamento via Ingress/Gateway dentro do cluster.
- Paridade observável com o driver Docker, do ponto de vista do portal e do editor do sistema
  (capabilities `container-lifecycle` e `app-serving` inalteradas na superfície).

**Non-Goals:**
- Suporte a um cluster gerenciado real (EKS/GKE/AKS) nesta change — fica para quando o `kind`
  validar a abstração, igual ao próprio roadmap já sequencia.
- Reconciliação via watch/informers — o driver Kubernetes usa polling nesta etapa.
- Resolver a lacuna de `pids_limit` (ex.: RuntimeClass com gVisor/kata) — aceita como limitação
  documentada, não bloqueante.
- Gateway API especificamente — Ingress padrão do Traefik é aceitável se mais simples de validar
  primeiro; a escolha entre os dois é um detalhe de implementação desta change, não uma mudança de
  especificação (nenhuma capability exige um ou outro).
- Migrar sistemas já provisionados pelo driver Docker para o driver Kubernetes — fora de escopo;
  o driver ativo é fixado por configuração da plataforma, não por sistema.

## Decisions

### D1 — Interface de driver extraída de `provisioning.py`, não reescrita do zero
`provisioning.py` hoje é uma função monolítica. Em vez de reescrever o fluxo de provisionamento,
extraímos uma interface (`ProvisioningDriver` ou nome equivalente) com os métodos que o código
Docker-específico já implementa implicitamente: `provision_system`, `remove_container_if_exists`,
`reconcile`, mais os dois sidecars. O driver Docker existente passa a implementar essa interface
sem mudar comportamento (mesma lógica, só reorganizada); o driver Kubernetes é a segunda
implementação. Alternativa rejeitada: um branch `if driver == "kubernetes"` disperso dentro da
função atual — não dá uma fronteira testável nem permite os dois drivers coexistirem com
confiança de que um não quebra o outro.

### D2 — Pod único por sistema com três containers, replicando o padrão de sidecar por netns
O `network_mode: container:<id>` de hoje é, conceitualmente, "estes processos compartilham
network namespace" — exatamente o que um Pod garante por construção para todos os seus
containers, sem a dependência de ordem que existe no Docker (não é preciso que o container do
agente exista primeiro para os sidecars descobrirem um ID). O Pod tem três containers: agente,
`dbgate`, `httpsproxy`. Alternativa rejeitada: three Pods separados com uma rede k8s compartilhada
(NetworkPolicy abrindo exceção) — mais superfície de rede exposta do que o modelo atual, e perde a
garantia "só os três se enxergam" que o netns compartilhado dá de graça.

### D3 — PVC + StorageClass para o workspace; ConfigMap para os arquivos de config
Decisão original (exploração): PVC em vez de hostPath/extraMounts, para que o mesmo manifesto
funcione em qualquer cluster depois (só a StorageClass muda por ambiente). `kind` já traz
`standard` (local-path-provisioner) como StorageClass default, então a validação local não exige
nenhum provisionador extra.

**Refinamento durante a implementação (task 3, achado real)**: um PVC do `local-path-provisioner`
fica num `hostPath` dentro do **nó** do cluster — que no `kind` é ele mesmo um container Docker,
não o host real onde o portal roda. Diferente do driver Docker (bind mount: o portal e o
container do sistema compartilham o mesmo diretório do host), o portal não tem nenhum caminho de
filesystem compartilhado com um PVC do cluster. Escrever os arquivos de config
(`opencode.json`/`agent-profile.json`/etc., sempre somente-leitura pro agente) direto num PVC
não é viável sem um mecanismo adicional.

Resolvido com o usuário: os arquivos de config vão num **ConfigMap**, criado/atualizado pelo
driver via a API do Kubernetes (que o portal já alcança para tudo o resto), montado como volume
somente-leitura no Pod — mesmo papel que o bind mount `ro` tem hoje no driver Docker, só que
entregue por API em vez de por filesystem compartilhado. PVC continua sendo a escolha certa só
para o **workspace** (grande, read-write, precisa persistir entre recriações do Pod — o ConfigMap
tem teto de tamanho e não serve pra isso). Alternativa rejeitada: PVC também para config com um
init container copiando o conteúdo — exigiria um segundo mecanismo de entrega até o init
container, sem ganhar nada sobre o ConfigMap direto.

### D4 — Traefik dentro do cluster, kind expõe via `extraPortMappings`
Decisão já fechada na exploração. O file provider do Traefik continua sendo a forma de descobrir
rotas (menos mudança de lógica), mas resolvendo o hostname como Service DNS
(`appaiforge-sys-<slug>.<namespace>.svc.cluster.local`) em vez do DNS do bridge Docker — ou,
alternativa dentro do mesmo objetivo, um Ingress/IngressRoute por sistema gerado pelo driver, com
o Traefik já instalado no cluster como Ingress controller. A escolha entre file-provider-apontando-
pro-cluster e Ingress-nativo-do-Traefik é resolvida durante a implementação (tasks.md), ambas
satisfazem a capability `container-driver-kubernetes` da mesma forma observável.

### D5 — `pids_limit`: limitação aceita, não mitigada nesta etapa
Decisão já fechada na exploração. Documentada na capability `container-driver-kubernetes`
("Limites de recursos mapeados para o Pod") e na modificação de `container-lifecycle` ("melhor-
esforço sob driver sem bloqueio rígido"). Sem RuntimeClass alternativo (gVisor/kata) nesta etapa —
adiciona complexidade operacional (outro runtime a instalar e manter no cluster) desproporcional
ao objetivo de validar a abstração num `kind` local.

### D6 — Reconciliação por polling, não watch/informers
Mantém o mesmo modelo que o driver Docker já usa (`reconcile()` varre e compara), só troca a fonte
(API do Kubernetes em vez do SDK do Docker). Menor escopo, revisitável sem mudar a interface do
driver nem o comportamento especificado — um watch/informer é uma otimização de implementação do
mesmo contrato (`container-driver-kubernetes`: "Pod ausente é recriado"), não uma mudança de
comportamento.

## Risks / Trade-offs

- **[Risco] Interface de driver extraída incorretamente, vazando detalhe Docker-específico pra
  camada comum** → Mitigação: a extração roda primeiro com o driver Docker sozinho atrás da nova
  interface (sem nenhuma mudança de comportamento), validada pela suíte de testes de integração já
  existente antes de escrever uma linha do driver Kubernetes.
- **[Risco] `pids_limit` mais fraco é uma regressão real de postura de segurança** → Mitigação:
  documentado explicitamente nas specs (`container-driver-kubernetes`, `container-lifecycle`) como
  limitação conhecida, não lacuna silenciosa; reavaliar antes de qualquer migração a cluster real
  de produção.
- **[Risco] `kind` difere de um cluster gerenciado o bastante pra esconder problemas** (sem
  cloud LB real, rede do Docker Desktop/host em vez de VPC) → Mitigação: aceito como limitação da
  etapa — o objetivo desta change é validar a abstração de driver, não a paridade total com
  EKS/GKE; o roadmap já sequencia isso pra depois (etapa 8 completa, fora desta change).
- **[Trade-off] Dois PVCs (ou um com subpaths) por sistema é mais objeto k8s pra gerenciar do que
  um bind mount** → Aceito: é o preço da portabilidade decidida em D3.

## Migration Plan

- Sem migração de sistemas existentes: o driver ativo é configuração da plataforma, fixada antes
  de provisionar um sistema — sistemas já provisionados pelo driver Docker continuam nele.
- Rollout: a interface de driver entra primeiro com o driver Docker como única implementação
  (sem mudança observável, risco zero); o driver Kubernetes entra depois, atrás de uma flag de
  configuração, validado contra `kind` antes de qualquer uso real.
- Rollback: desativar a flag do driver Kubernetes volta ao comportamento atual sem efeito nos
  sistemas já provisionados por Docker.

## Open Questions

- Ingress nativo do Traefik vs. file-provider-apontando-pro-cluster (D4) — resolvido em tasks.md,
  não muda o comportamento especificado nem a interface do driver.
- Um PVC com dois subpaths vs. dois PVCs por sistema (D3) — mesma situação, detalhe de
  implementação sem impacto observável.
