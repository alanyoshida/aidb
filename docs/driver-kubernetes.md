# Driver Kubernetes (instalação alternativa, validação local)

← [README](../README.md)

O driver de provisionamento padrão é o Docker ([instalação principal](../README.md#instalação)). Existe também um **driver Kubernetes**
(`APPAIFORGE_PROVISIONING_DRIVER=kubernetes`, capability `container-driver-kubernetes`,
[roadmap etapa 8](roadmap-confinamento-do-agente.md)), que materializa cada sistema como um
Pod — hoje validado só contra um cluster `kind` local, nunca contra um cluster gerenciado real
(EKS/GKE/AKS).

Quando o driver ativo é Kubernetes, o próprio portal (e seu Postgres) também roda dentro do
cluster — instale os dois com o chart Helm em [`deploy/helm/appaiforge-portal/`](../deploy/helm/appaiforge-portal):

```bash
docker build -f deploy/portal.Dockerfile -t appaiforge/portal:0.1.0 .
kind load docker-image appaiforge/portal:0.1.0 --name appaiforge-dev   # nome do cluster kind de validação

helm install appaiforge-portal deploy/helm/appaiforge-portal \
  --namespace appaiforge --create-namespace \
  --kube-context kind-appaiforge-dev
```

Pré-requisito: o cluster `kind` já criado com Traefik como Ingress controller — ver
`openspec/changes/archive/2026-11-11-add-kubernetes-driver/kind-cluster.yaml` e
`traefik-values.yaml`. Esse values define `deployment.dnsPolicy: ClusterFirstWithHostNet`: o Traefik
roda com `hostNetwork` e, sem isso, não resolve o DNS do Service do portal, que o `forwardAuth` de
cada rota `/apps/{slug}` chama ([ADR 0027](adr/0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md)
— sintoma: as apps respondem 500 e o log do Traefik mostra `lookup … server misbehaving`). Ele também
usa rollout `maxSurge: 0`, porque num nó só o pod novo não agenda enquanto o antigo segura as portas
80/443.

Atualizar um portal já instalado que tenha schema criado sem Alembic (sem `alembic_version`): carimbe
a revisão anterior e aplique as novas antes de reiniciar, num pod avulso com a imagem nova —
`alembic stamp b4c5d6e7f8a9 && alembic upgrade head` em `/app/portal`. Detalhes de valores, teardown e o que o chart não cobre (broker de
inferência, telemetria) ficam no [README do chart](../deploy/helm/appaiforge-portal/README.md). Os
manifests antigos, aplicados manualmente com `kubectl apply`, continuam em
`openspec/changes/archive/2026-11-14-deploy-portal-in-cluster/` só como histórico da decisão — o
chart é a forma recomendada de instalar hoje.
