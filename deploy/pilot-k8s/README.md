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

# 2. Cluster de produção. O kind troca o contexto atual do kubeconfig: volte ao seu depois.
#    O Traefik vem com o chart do portal (passo 5), não é mais instalado à parte.
kind create cluster --config deploy/pilot-k8s/kind-cluster.yaml
kubectl config use-context <seu-contexto>
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
     -f deploy/pilot-k8s/values-pilot.yaml -f deploy/pilot-k8s/traefik-values.yaml \
     --set image.tag=pilot --set image.pullPolicy=Never \
     --set portal.baseImage=registro.pilot.test/appaiforge/base:1.4.2 --wait
   ```

   O [`traefik-values.yaml`](traefik-values.yaml) configura o subchart do Traefik para o `kind`
   (`hostNetwork` nas portas 80/443 do nó, DNS do cluster, rollout sem sobreposição) e põe os
   listeners do `Gateway` nessas portas. O modo de roteamento é o padrão (`ingressroute`); para o
   modo `gateway`, acrescente `--set routing.mode=gateway`.

### Piloto montado antes do Traefik no chart

Até a change `gateway-api-traefik-subchart`, o Traefik era um release `traefik` à parte, que
disputaria as portas 80/443 com o do chart. O `helm upgrade` não instala os CRDs de `crds/` (o
Helm só faz isso no `helm install`): aplique os da Gateway API antes, desinstale o Traefik antigo e
atualize o portal:

```bash
kubectl --context kind-aidb-prod apply --server-side -f deploy/helm/appaiforge-portal/crds/
helm --kube-context kind-aidb-prod uninstall traefik -n traefik
helm --kube-context kind-aidb-prod upgrade aidb-prod deploy/helm/appaiforge-portal -n aidb-prod \
  -f deploy/pilot-k8s/values-pilot.yaml -f deploy/pilot-k8s/traefik-values.yaml \
  --set image.tag=pilot --set image.pullPolicy=Never \
  --set portal.baseImage=registro.pilot.test/appaiforge/base:1.4.2 --wait
```

Os CRDs do Traefik já existem no cluster (vieram do release antigo) e ficam como estão. Sem os da
Gateway API, o `upgrade` falha em `no matches for kind "GatewayClass"`. A entrada fica fora do ar
entre o `uninstall` e o Traefik novo ficar pronto (cerca de um minuto no piloto). No primeiro boot,
o portal republica as rotas dos sistemas ativos.

## Homologação com LLM real

A stack sobe a homologação com o agente simulado. Para usar o agente real (`opencode`):

```bash
docker compose -f deploy/docker-compose.e2e-gitlab.yml -f deploy/pilot-k8s/homolog-llm.yml up -d --no-deps portal
```

Depois, como admin, cadastre a chave de um provedor em **Administração** e crie sistemas novos com
esse provedor. Os sistemas criados pela jornada de teste têm uma conexão com senha falsa e não
servem para o agente real.

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
- **Registro privado.** Os Pods de sistema não declaravam `imagePullSecrets`. Corrigido depois:
  `portal.systemImagePullSecrets` no chart.
- **O `kind create cluster` troca o contexto atual** do kubeconfig para o cluster novo.

## Achados (2026-11-22, change `gateway-api-traefik-subchart`)

- **`helm upgrade` não instala CRDs.** Atualizar o piloto para o chart com o Traefik como subchart
  falhou em `no matches for kind "GatewayClass"`: o Helm só aplica `crds/` no `helm install`.
  Corrigido no passo a passo acima (aplicar os CRDs antes) e em `docs/operacao.md`.
- **Rota de sistema ativo que faltava.** O sistema `base-registro` estava ativo sem `IngressRoute`
  (a reconciliação nunca roda no boot). A republicação das rotas no boot, nova nesta change,
  recriou a rota na primeira subida.
- **Troca de modo no piloto.** `ingressroute` → `gateway` → `ingressroute` com `helm upgrade
  --reuse-values --set routing.mode=...`: portal, webhook e as apps dos quatro sistemas responderam
  pela rota nos dois modos (302 sem sessão, 200 com a do admin de emergência), sem recriar os Pods.
- **Jornada nos dois modos.** Com a homologação de volta ao agente simulado (sem
  `homolog-llm.yml`), `AIDB_PILOT_K8S=1 uv run pytest tests/e2e_gitlab/test_pilot_kubernetes.py`
  passou no modo `ingressroute` e, depois de `--set routing.mode=gateway`, no modo `gateway`
  (tag → implantação manual, webhook do GitLab, volta à versão anterior). Na troca, o boot do
  portal republicou as rotas de todos os sistemas ativos, inclusive o criado pela rodada anterior.
  Essa rodada usou o piloto já existente, atualizado pelo chart novo.
- **Piloto do zero pelo README.** Os passos 2 a 5 num cluster novo (`aidb-prod2`, porta 28081,
  apelido `aidb-prod2.pilot.test`, para não apagar o `aidb-prod`), com a homologação do passo 1 já
  de pé: o `helm install` com `traefik-values.yaml` subiu o portal, o Postgres e o Traefik do
  subchart na primeira tentativa, com os 10 CRDs da Gateway API. A jornada passou no modo
  `ingressroute` e, depois do `helm upgrade --set routing.mode=gateway`, no modo `gateway`. Ela
  aceita outro cluster por `AIDB_PILOT_CONTEXT`, `AIDB_PILOT_HOST` e `AIDB_PILOT_PORT`.
