# Portal dentro do cluster `kind` — driver Kubernetes

Faz o portal (e o Postgres dele) rodar como workload dentro do mesmo cluster `kind` de
validação do driver Kubernetes (change `add-kubernetes-driver`, arquivada em
`openspec/changes/archive/2026-11-11-add-kubernetes-driver/`) — só necessário quando o driver
ativo é Kubernetes; o `docker-compose` de produção (driver Docker) não muda em nada. Ver
`design.md` para as decisões e `proposal.md` para o porquê.

## Pré-requisitos

- O mesmo cluster `kind` da change anterior já criado e com Traefik instalado — ver o README
  dela se ainda não tiver feito isso.
- Docker rodando (a imagem do portal é construída e carregada no `kind` via
  `kind load docker-image`, igual às imagens dos sistemas).

## Setup

Da raiz do repositório, nesta ordem (cada manifesto depende do anterior):

```bash
kubectl --context kind-appaiforge-dev create namespace appaiforge
kubectl --context kind-appaiforge-dev apply -f openspec/changes/deploy-portal-in-cluster/portal-rbac.yaml
kubectl --context kind-appaiforge-dev apply -f openspec/changes/deploy-portal-in-cluster/portal-postgres.yaml
kubectl --context kind-appaiforge-dev -n appaiforge wait --for=condition=ready pod/appaiforge-portal-postgres-0 --timeout=90s

docker build -f deploy/portal.Dockerfile -t appaiforge/portal:0.1.0 .
kind load docker-image appaiforge/portal:0.1.0 --name appaiforge-dev

kubectl --context kind-appaiforge-dev apply -f openspec/changes/deploy-portal-in-cluster/portal-deployment.yaml
kubectl --context kind-appaiforge-dev -n appaiforge rollout status deployment/appaiforge-portal --timeout=90s
```

Confirmar que subiu:

```bash
kubectl --context kind-appaiforge-dev -n appaiforge run health-check --rm -i --restart=Never \
  --image=curlimages/curl --command -- curl -s -o /dev/null -w "%{http_code}\n" \
  http://appaiforge-portal:8080/api/health
```

Deve responder `200`.

## Notas

- `portal-rbac.yaml` dá à `ServiceAccount` do portal exatamente as permissões que
  `kubernetes_driver.py`/`checkpoints.py` usam (nem mais, nem menos) — ver os comentários do
  próprio arquivo. O único recurso cluster-scoped é `namespaces` (usado só por
  `ensure_ready()`); se preferir não conceder isso, crie o namespace manualmente (passo acima) e
  remova o `ClusterRole`/`ClusterRoleBinding` do arquivo.
- `portal-deployment.yaml` fixa `APPAIFORGE_HARNESS_MODE=fake` por padrão (mesmo default do
  `docker-compose`). Para testar chat real com o driver Kubernetes, troque pra `opencode` (ou use
  o roteiro do teste `test_sistema_k8s_ponta_a_ponta_com_portal_dentro_do_cluster`, que não
  depende dessa env — monta o `AgentQueue` direto).
- Igual ao cluster `kind` em si, isto é só para validação local — nunca para produção. Teardown:
  `kubectl --context kind-appaiforge-dev delete namespace appaiforge` remove tudo (Deployment,
  Postgres, RBAC, e qualquer sistema provisionado dentro desse namespace).
