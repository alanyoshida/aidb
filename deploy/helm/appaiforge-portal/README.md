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

- Um cluster Kubernetes. O chart instala o Traefik como subchart (`traefik.enabled=true`, padrão),
  com os CRDs dele e os da Gateway API (canal standard, v1.6.3). Num cluster que já tem um Traefik,
  desligue o subchart (`traefik.enabled=false`); no modo `gateway`, informe então o `Gateway` dele
  em `gateway.existing`. Ver [Roteamento](#roteamento).
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
port-forward`, já que por padrão este chart não cria rota para o próprio portal) e a credencial do
admin semeado em dev.

## Valores principais

| Valor | Default | O quê |
|---|---|---|
| `image.repository` / `image.tag` | `appaiforge/portal` / `0.1.0` | imagem do portal |
| `portal.harnessMode` | `fake` | `fake` = sem LLM real (dev/E2E); `opencode` = chat real |
| `portal.baseImage` | `appaiforge/base:0.1.0` (padrão do portal) | imagem dos Pods de sistema |
| `portal.claudeCodeImage` | `appaiforge/claude-code:0.1.0` (padrão do portal) | imagem dos sistemas com o perfil de agente `claude-code` |
| `portal.systemImagePullSecrets` | `[]` | Secrets de pull dos Pods de sistema (registro privado), criados no namespace dos sistemas |
| `portal.systemsNamespace` | namespace da release | onde o driver provisiona os Pods de sistema; a Role do portal é criada nele, e um namespace diferente do da release precisa existir antes do `helm install` |
| `portal.seedDemoAdmin` | `true` | semeia `admin@appaiforge.local` / `admin123` (nunca em produção) |
| `portal.dbGate.mode` | `enforce` | `enforce` recusa bloqueada/confirmável na hora; `shadow` só audita |
| `rbac.clusterScoped` | `true` | concede o `ClusterRole` de `namespaces` (get/create) usado por `ensure_ready()`; desligue para criar o namespace dos sistemas manualmente e não conceder isso ao `ServiceAccount` do portal |
| `secrets.existingSecret` | `""` | nome de um `Secret` já criado fora do Helm (chaves `secretKey`, `dbGateProxyServiceToken`, `postgresPassword`) — use em produção em vez dos defaults de dev em `secrets.*` |
| `portal.installationRole` | `development` | `production` só aceita sistemas só implantação; exige `portal.seedDemoAdmin=false` e `secrets.existingSecret` (o chart recusa renderizar sem eles) |
| `portal.webhookBaseUrl` | `""` | endereço do portal como o GitLab o vê, mostrado na aba Implantação para o webhook (vazio = `auth.publicBaseUrl`) |
| `portal.deploy.pollInterval` / `.healthTimeout` / `.healthInterval` | `60` / `90` / `2` | consulta de tags novas e checagens de saúde da implantação (só com papel `production`) |
| `portal.migrateOnStart` | `false` | initContainer com `alembic upgrade head` antes de cada subida do portal; ligue numa instalação nova (não num banco criado antes sem Alembic) |
| `routing.mode` | `ingressroute` | modo de roteamento de `/apps/<slug>` e da rota do portal: `ingressroute` (IngressRoute + Middleware do Traefik, como antes) ou `gateway` (HTTPRoute da Gateway API). Transitório: ver [Roteamento](#roteamento) |
| `traefik.enabled` | `true` | instala o Traefik como subchart (`traefik/traefik` 42.3.2), com os providers de CRDs e de Gateway API e o `GatewayClass` `traefik`; os demais valores de `traefik.*` vão para o chart dele |
| `gateway.listenerPorts.web` / `.websecure` | `8000` / `8443` | portas dos listeners do `Gateway` deste chart (modo `gateway` com `traefik.enabled`); têm de ser as portas dos entrypoints do Traefik (`traefik.ports.*.port`) |
| `gateway.existing.name` / `.namespace` | `""` / `""` | `Gateway` já existente, obrigatório no modo `gateway` com `traefik.enabled=false` |
| `portalRoute.enabled` / `.host` / `.entryPoints` / `.tlsSecretName` | `false` / `""` / `[web]` / `""` | rota do próprio portal, necessária para o webhook do GitLab. Modo `ingressroute`: `IngressRoute` com prioridade 1, `entryPoints` e `tls.secretName`. Modo `gateway`: `HTTPRoute` no `Gateway`, com o TLS no listener HTTPS do `Gateway` deste chart. Nos dois, as rotas `/apps/<slug>` continuam ganhando |
| `postgres.persistence.size` / `.storageClassName` | `1Gi` / default da classe do cluster | PVC do Postgres do portal (sempre criado — a spec `container-driver-kubernetes` exige persistência dos dados operacionais) |

Veja [`values.yaml`](values.yaml) para a lista completa, comentada.

## Portal de produção

Um portal de produção só serve sistemas só implantação (sem agente, sem chat, sem credencial de
LLM). O exemplo [`values-production.yaml`](values-production.yaml) liga o papel `production`,
desliga o admin de demonstração, lê os segredos de um `Secret` criado fora do Helm e liga a rota
do portal. Instale cada portal no seu próprio namespace. Por padrão, os Pods de sistema ficam
no namespace da release; para separá-los, defina `portal.systemsNamespace` com um namespace
criado antes do `helm install`. A Role do portal é criada no namespace dos sistemas. Dois portais
nunca devem usar o mesmo namespace de sistemas, porque disputariam os mesmos Pods.

```bash
kubectl create namespace aidb-prod
kubectl -n aidb-prod create secret generic aidb-prod-portal-secrets \
  --from-literal=secretKey="$(openssl rand -hex 32)" \
  --from-literal=dbGateProxyServiceToken="$(openssl rand -hex 32)" \
  --from-literal=postgresPassword="$(openssl rand -hex 16)" \
  --from-literal=breakglassPasswordHash='<saída de appaiforge hash-password>'
helm install aidb-prod deploy/helm/appaiforge-portal -n aidb-prod \
  -f deploy/helm/appaiforge-portal/values-production.yaml
```

O passo a passo completo (primeiro acesso, GitLab, webhook, atualização e backup) está em
[`docs/operacao.md`](../../../docs/operacao.md#instalar-um-portal-de-produção).

## Roteamento

O Traefik atende as rotas nos dois modos; o que muda é o tipo de objeto. Nos dois, a autenticação
das apps é o mesmo `Middleware` `forwardAuth` do Traefik.

| | `ingressroute` (padrão) | `gateway` |
|---|---|---|
| rota de cada app | `IngressRoute` + `Middleware` `stripPrefix` | `HTTPRoute` com `ExtensionRef` (auth) e `URLRewrite` |
| rota do portal | `IngressRoute`, prioridade 1 | `HTTPRoute`; as rotas das apps levam o mesmo host |
| TLS do portal | `tls.secretName` na rota | listener HTTPS do `Gateway` |
| `Gateway` | nenhum | o deste chart, ou `gateway.existing` |

Os dois modos convivem só nesta versão: uma versão seguinte remove o `ingressroute` e passa o
padrão para `gateway`. Para trocar, `helm upgrade ... --set routing.mode=gateway`; logo
depois de subir, a reconciliação do portal republica as rotas dos sistemas no modo novo e apaga as
do outro, sem recriar os Pods. Voltar é o mesmo comando com `ingressroute`.

**Cluster que já tem Traefik instalado à parte** (como o piloto antes desta versão): dois Traefik
disputariam as mesmas portas. Desinstale o release antigo antes do `helm upgrade`, ou use
`traefik.enabled=false` — no modo `gateway`, com o provider `kubernetesGateway` ligado nesse
Traefik e `gateway.existing` apontando para um `Gateway` dele.

**CRDs**: o Helm instala os CRDs de `crds/` (os da Gateway API e os do Traefik) só no
`helm install` e nunca os atualiza nem remove. Ao atualizar com `helm upgrade` uma instalação de
antes do Traefik no chart, aplique-os antes (`kubectl apply --server-side -f
deploy/helm/appaiforge-portal/crds/`), ou o upgrade falha por falta do kind `GatewayClass`. Ao trocar a versão do Traefik, atualize-os à mão
(ver [`docs/operacao.md`](../../../docs/operacao.md)).

## Teardown

```bash
helm uninstall appaiforge-portal -n appaiforge
# o StatefulSet não apaga sozinho o PVC do Postgres:
kubectl -n appaiforge delete pvc -l app.kubernetes.io/instance=appaiforge-portal
```

## O que este chart não faz

- Não expõe o portal por padrão — só `port-forward`. Com `portalRoute.enabled=true` cria a rota
  dele no modo de roteamento escolhido (necessária num portal de produção, para usuários e para o
  webhook).
- Não atualiza os CRDs da Gateway API nem os do Traefik depois da primeira instalação (limitação do
  Helm; ver [Roteamento](#roteamento)).
- Não implanta o broker de inferência (LiteLLM) nem telemetria OTel — fora do escopo da validação
  do driver Kubernetes; use o `docker-compose` (driver Docker) para isso.
