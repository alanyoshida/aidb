# appaiforge-portal (Helm chart)

Instala o portal AIDB e seu Postgres operacional dentro de um cluster Kubernetes, sob o
**driver de provisionamento Kubernetes** (capability `container-driver-kubernetes`) — equivalente
em Helm aos três manifests que antes eram aplicados manualmente em
[`openspec/changes/archive/2026-11-14-deploy-portal-in-cluster/`](../../../openspec/changes/archive/2026-11-14-deploy-portal-in-cluster)
(mantidos lá só como histórico da decisão, não mais a forma recomendada de instalar).

Só faz sentido quando o driver ativo é `kubernetes`. O `docker-compose` de produção (driver
Docker, `deploy/docker-compose.yml`) não tem nenhuma relação com este chart.

> Como o cluster `kind` de validação em si, este chart é para **validação local** — nunca testado
> contra um cluster gerenciado real (EKS/GKE/AKS). Ver `docs/roadmap-confinamento-do-agente.md`,
> etapa 8.

## Pré-requisitos

- Um cluster Kubernetes com Traefik instalado como Ingress controller (CRDs `IngressRoute`/
  `Middleware`) — ver `openspec/changes/archive/2026-11-11-add-kubernetes-driver/kind-cluster.yaml`
  e `traefik-values.yaml` para como isso foi montado no `kind` de validação.
- A imagem do portal construída e carregada no cluster (no `kind`, via `kind load docker-image`,
  igual às imagens dos sistemas):

  ```bash
  docker build -f deploy/portal.Dockerfile -t appaiforge/portal:0.1.0 .
  kind load docker-image appaiforge/portal:0.1.0 --name appaiforge-dev
  ```

## Instalar

```bash
helm install appaiforge-portal deploy/helm/appaiforge-portal \
  --namespace appaiforge --create-namespace \
  --kube-context kind-appaiforge-dev
```

A saída do `helm install` (ou `helm status appaiforge-portal -n appaiforge`) traz os próximos
passos: como confirmar que o portal respondeu (`/api/health`), como acessá-lo (`kubectl
port-forward`, já que este chart não cria `IngressRoute` para o próprio portal) e a credencial do
admin semeado em dev.

## Valores principais

| Valor | Default | O quê |
|---|---|---|
| `image.repository` / `image.tag` | `appaiforge/portal` / `0.1.0` | imagem do portal |
| `portal.harnessMode` | `fake` | `fake` = sem LLM real (dev/E2E); `opencode` = chat real |
| `portal.systemsNamespace` | namespace da release | onde o driver provisiona os Pods de sistema |
| `portal.seedDemoAdmin` | `true` | semeia `admin@appaiforge.local` / `admin123` (nunca em produção) |
| `portal.dbGate.mode` | `enforce` | `enforce` recusa bloqueada/confirmável na hora; `shadow` só audita |
| `rbac.clusterScoped` | `true` | concede o `ClusterRole` de `namespaces` (get/create) usado por `ensure_ready()`; desligue para criar o namespace dos sistemas manualmente e não conceder isso ao `ServiceAccount` do portal |
| `secrets.existingSecret` | `""` | nome de um `Secret` já criado fora do Helm (chaves `secretKey`, `dbGateProxyServiceToken`, `postgresPassword`) — use em produção em vez dos defaults de dev em `secrets.*` |
| `postgres.persistence.size` / `.storageClassName` | `1Gi` / default da classe do cluster | PVC do Postgres do portal (sempre criado — a spec `container-driver-kubernetes` exige persistência dos dados operacionais) |

Veja [`values.yaml`](values.yaml) para a lista completa, comentada.

## Teardown

```bash
helm uninstall appaiforge-portal -n appaiforge
# o StatefulSet não apaga sozinho o PVC do Postgres:
kubectl -n appaiforge delete pvc -l app.kubernetes.io/instance=appaiforge-portal
```

## O que este chart não faz

- Não instala Traefik nem RBAC/CRDs dele — isso é pré-requisito do cluster, não do portal.
- Não expõe o portal via `Ingress`/`IngressRoute` — só `port-forward` (o portal em si nunca
  precisou de rota publicada; quem usa `IngressRoute` são os sistemas provisionados pelo driver).
- Não implanta o broker de inferência (LiteLLM) nem telemetria OTel — fora do escopo da validação
  do driver Kubernetes; use o `docker-compose` (driver Docker) para isso.
