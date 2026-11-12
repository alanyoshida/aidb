# Cluster `kind` de validação — driver Kubernetes

Ambiente local para validar o driver de provisionamento Kubernetes (change
`add-kubernetes-driver`, etapa 8 do roadmap de confinamento) antes de qualquer cluster gerenciado
real. Ver `design.md` para as decisões (PVC+StorageClass, Traefik dentro do cluster) e
`kind-cluster.yaml` para a configuração do cluster.

## Pré-requisitos

- `kind` e `kubectl` instalados e no `PATH`.
- Docker rodando (os nós do `kind` são containers Docker).
- Nenhum outro processo ocupando as portas do host `18080`/`18443` (usadas pelo Ingress do
  Traefik dentro do cluster — não usamos `8080`/`8443` porque outros serviços deste ambiente já
  os ocupam; achado real ao criar o cluster pela primeira vez, ver task 2.1 em `tasks.md`).

## Setup

Da raiz do repositório:

```bash
kind create cluster --config openspec/changes/add-kubernetes-driver/kind-cluster.yaml
```

Confirmar que o nó subiu:

```bash
kubectl --context kind-appaiforge-dev get nodes
```

Deve mostrar `appaiforge-dev-control-plane` em `Ready` (pode levar ~20s depois do comando
anterior terminar — o CNI ainda está instalando).

Confirmar a StorageClass default (`standard`, via `local-path-provisioner`, já vem instalada pelo
`kind` — nenhum provisionador extra a instalar):

```bash
kubectl --context kind-appaiforge-dev get storageclass
```

## Teardown

```bash
kind delete cluster --name appaiforge-dev
```

Remove o cluster inteiro (todos os nós, volumes do `local-path-provisioner` inclusive) e limpa a
entrada correspondente do kubeconfig. Não afeta nenhum outro cluster `kind` já registrado na
máquina (cada cluster `kind` é isolado pelo próprio nome).

## Notas

- `kind create cluster` troca o `current-context` do `kubectl` para `kind-appaiforge-dev`. Se
  você tinha outro contexto ativo antes, troque de volta com `kubectl config use-context
  <contexto-anterior>` depois do teardown, ou sempre passe `--context kind-appaiforge-dev`
  explicitamente nos comandos deste cluster (como este documento faz).
- Este cluster é só para validar o driver localmente — nunca para produção. O roadmap já previa
  isso: `kind` primeiro, cluster gerenciado real (EKS/GKE/AKS) depois, fora desta change.
