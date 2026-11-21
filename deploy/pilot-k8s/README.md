# Piloto: portal de produção num cluster Kubernetes próprio

Monta, numa máquina só, o fluxo completo homologação → GitLab → tag → produção, com a produção num
cluster `kind` dedicado (`aidb-prod`), instalada pelo chart com `values-production.yaml`, como um
operador faria seguindo [Instalar um portal de produção](../../docs/operacao.md#instalar-um-portal-de-produção).

| Peça | Onde |
|---|---|
| GitLab, runner e portal de homologação (driver Docker) | stack `deploy/docker-compose.e2e-gitlab.yml`, homologação em `http://localhost:8083` |
| Portal de produção (driver Kubernetes) | cluster `kind-aidb-prod`, namespace `aidb-prod`, em `http://aidb-prod.pilot.test:28080` |

O nó do cluster entra na rede Docker do GitLab com o apelido `aidb-prod.pilot.test`: os Pods leem o
repositório em `gitlab:22`, e o GitLab chama o webhook em `http://aidb-prod.pilot.test`.

## Montar

```bash
# 1. GitLab e homologação (sem o portal de produção da stack)
docker compose -f deploy/docker-compose.e2e-gitlab.yml up -d --build postgres portal traefik gitlab gitlab-runner
python3 deploy/e2e-gitlab/init.py

# 2. Cluster de produção com Traefik. O kind troca o contexto atual do kubeconfig: volte ao seu depois.
kind create cluster --config deploy/pilot-k8s/kind-cluster.yaml
kubectl config use-context <seu-contexto>
helm --kube-context kind-aidb-prod install traefik traefik/traefik --version 42.3.2 \
  -n traefik --create-namespace -f deploy/pilot-k8s/traefik-values.yaml --wait
docker network connect --alias aidb-prod.pilot.test appaiforge-e2e-gitlab-net aidb-prod-control-plane

# 3. Imagens: a base com um nome de registro, para exercitar portal.baseImage
docker build -t appaiforge/base:0.1.0 -f base-image/Dockerfile base-image
docker tag appaiforge/base:0.1.0 registro.pilot.test/appaiforge/base:1.4.2
docker build -t appaiforge/portal:pilot -f deploy/portal.Dockerfile .
kind load docker-image registro.pilot.test/appaiforge/base:1.4.2 appaiforge/portal:pilot --name aidb-prod
```

4. Namespace, Secret e valores, como no guia de operação. Gere a senha do admin de emergência e
   guarde-a em `deploy/pilot-k8s/pilot.env` (ignorado pelo git), que o teste lê:

   ```
   PILOT_BREAKGLASS_EMAIL=admin@pilot.test
   PILOT_BREAKGLASS_PASSWORD=<senha>
   ```

   Crie o namespace `aidb-prod` e o Secret `aidb-prod-portal-secrets`, com o hash dessa senha
   (`cd portal && uv run appaiforge hash-password`). Copie `values-production.yaml` para
   `deploy/pilot-k8s/values-pilot.yaml`, também ignorado, e troque:
   - o host por `aidb-prod.pilot.test`;
   - `auth.publicBaseUrl` por `http://aidb-prod.pilot.test:28080`;
   - `portal.webhookBaseUrl` por `http://aidb-prod.pilot.test`;
   - o e-mail por `admin@pilot.test`.

5. Instale:

   ```bash
   helm --kube-context kind-aidb-prod install aidb-prod deploy/helm/appaiforge-portal -n aidb-prod \
     -f deploy/pilot-k8s/values-pilot.yaml --set image.tag=pilot --set image.pullPolicy=Never \
     --set portal.baseImage=registro.pilot.test/appaiforge/base:1.4.2 --wait
   ```

## Rodar a jornada

```bash
cd portal && AIDB_PILOT_K8S=1 uv run pytest tests/e2e_gitlab/test_pilot_kubernetes.py
```

O teste repete a jornada de `test_deploy_only.py` com a produção no cluster:

1. A homologação envia o código, promove pelo merge request, e o pipeline cria a tag v1.
2. Na produção, o editor é criado pelo admin de emergência e cria o sistema só implantação.
3. O sistema recebe a chave só leitura. A v1 é recusada por falta da conexão `vendas` e, depois de cadastrada a conexão, é implantada.
4. A v2 chega sozinha pelo webhook do GitLab.
5. A volta manual para a v1 se mantém, mesmo com outra chamada do webhook.

## Desmontar

```bash
kind delete cluster --name aidb-prod
docker compose -f deploy/docker-compose.e2e-gitlab.yml down
```

## Achados (2026-11-21)

- **Imagem base dos sistemas fixa no código.** O container principal de cada sistema usava
  `appaiforge/base:0.1.0`, fixo no perfil do agente. `APPAIFORGE_BASE_IMAGE` só mudava os
  sidecars. Corrigido: o perfil padrão segue a imagem base configurada, e o chart ganhou
  `portal.baseImage`.
- **Guia de produção por Helm incompleto.** Ele não dizia qual imagem do portal usar, nem que a
  imagem base precisa estar no registro do cluster. Corrigido em `docs/operacao.md`.
- **Registro privado.** Os Pods de sistema não declaram `imagePullSecrets` e usam o ServiceAccount
  `default` do namespace dos sistemas. Anexe o Secret de pull a ele, como o guia agora diz.
- **O `kind create cluster` troca o contexto atual** do kubeconfig para o cluster novo.
