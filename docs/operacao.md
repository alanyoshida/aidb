# Operação

← [README](../README.md)

- **Rollback**: página do sistema → Checkpoints → Restaurar. Em sistema só implantação: aba Implantação → **Implantar** na tag anterior.
- **Portal de produção**: instalação própria (banco, volumes e Traefik) com `APPAIFORGE_INSTALLATION_ROLE=production`; recusa criar e provisionar sistema com agente, e um sistema com agente encontrado na reconciliação fica em erro com o motivo. Sob o driver Docker, recusa subir num host com containers de outra instalação. Passo a passo em [Instalar um portal de produção](#instalar-um-portal-de-produção).
- **Implantação interrompida**: se o portal reinicia no meio de uma implantação, ela fica como falha ("interrompida") na subida seguinte e o workspace volta ao commit da última implantação com sucesso.
- **Arquivar** (dono): para o container, preserva o workspace, remove a rota. **Excluir** (admin, só para arquivados): remove container + workspace.
- **Logs**: `docker compose logs -f portal` / `docker logs appaiforge-sys-<slug>`.
- **Saúde das conexões**: cada conexão é sondada periodicamente e exibe seu estado na página do sistema.
- **Auditoria**: toda ação de escrita da gestão (sistemas, conexões, usuários, provedores) fica numa trilha sem segredos, global para o admin e por sistema.
- **Estado da app**: o monitor marca `erro — app fora do ar` após 3 sondas falhas e recupera sozinho quando a app volta.
- **Reconciliação**: logo depois da subida (em segundo plano) e a cada `APPAIFORGE_RECONCILE_INTERVAL` segundos (padrão 300) o portal recria containers ou Pods ausentes ou divergentes (workspace persiste no bind ou na PVC), republica as rotas e checa a saúde das conexões. Um sistema recriado com sucesso volta a ativo; uma falha ao recriar deixa o sistema em erro com o motivo e é tentada de novo na passada seguinte.
- **Backup**: volumes do Postgres do portal + diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

## Instalar um portal de produção

O portal de produção só serve sistemas só implantação: roda as versões aprovadas no GitLab, sem agente, sem chat e sem credencial de LLM. O fluxo completo está em [Sistema só implantação](guia-de-uso.md#sistema-só-implantação). A preparação do GitLab (chave só leitura, tags e webhook) está em [GitLab, seção 7](gitlab.md#7-portal-de-produção-sistema-só-implantação).

### 1. Pré-requisitos

- **Host próprio.** Com o driver Docker, use um host Docker só deste portal. Ele recusa subir se encontrar containers de sistema de outra instalação, como a homologação, e lista quais são. Com o driver Kubernetes, instale num namespace só dele.
- **GitLab alcançável pelo portal**, por SSH, para ler o repositório de cada sistema.
- **Portal alcançável pelo GitLab**, só se for usar webhook. Sem isso, use a consulta periódica.
- Uma senha para o admin de emergência. O hash dela sai de `cd portal && uv run appaiforge hash-password`.

### 2a. Instalar por compose (driver Docker)

1. Construa a imagem base dos sistemas no host: `docker build -t appaiforge/base:0.1.0 -f base-image/Dockerfile base-image`.
2. Copie `deploy/production.env.example` para `deploy/production.env` e preencha:
   - **Obrigatórias:** `APPAIFORGE_SECRET_KEY`, `APPAIFORGE_DB_GATE_PROXY_SERVICE_TOKEN` e `APPAIFORGE_POSTGRES_PASSWORD`. O compose recusa subir sem elas.
   - **Admin de emergência:** `APPAIFORGE_BREAKGLASS_EMAIL` e `APPAIFORGE_BREAKGLASS_PASSWORD_HASH`. Ponha o hash entre aspas simples, porque ele tem `$`.
   - **Endereços:** `APPAIFORGE_PUBLIC_BASE_URL` e, se o GitLab vê o portal por outro endereço, `APPAIFORGE_WEBHOOK_BASE_URL`.

   O arquivo preenchido está no `.gitignore`: nunca o versione.
3. Crie o banco e aplique as migrações antes da primeira subida:

   ```bash
   docker compose -f deploy/docker-compose.production.yml --env-file deploy/production.env build portal
   docker compose -f deploy/docker-compose.production.yml --env-file deploy/production.env up -d postgres
   docker compose -f deploy/docker-compose.production.yml --env-file deploy/production.env run --rm --no-deps -w /app/portal portal alembic upgrade head
   ```

4. Suba o portal e o Traefik:

   ```bash
   docker compose -f deploy/docker-compose.production.yml --env-file deploy/production.env up -d --build
   ```

   O compose não tem broker de inferência, LiteLLM, banco de demonstração nem observabilidade. TLS fica com o que estiver na frente da porta `APPAIFORGE_HTTP_PORT`.

### 2b. Instalar por Helm (driver Kubernetes)

1. Crie o namespace e o Secret, com as chaves `secretKey`, `dbGateProxyServiceToken`, `postgresPassword` e `breakglassPasswordHash`. Os comandos estão no [README do chart](../deploy/helm/appaiforge-portal/README.md#portal-de-produção).
2. Publique no registro do cluster as imagens do portal (`deploy/portal.Dockerfile`) e a base dos sistemas (`base-image/Dockerfile`). Num `kind`, carregue-as com `kind load docker-image`.
3. Ajuste uma cópia de [`values-production.yaml`](../deploy/helm/appaiforge-portal/values-production.yaml):
   - imagem do portal (`image.repository` e `image.tag`) e imagem base dos sistemas (`portal.baseImage`; `portal.claudeCodeImage` para o perfil `claude-code`). Com registro privado, use `imagePullSecrets` para o portal e `portal.systemImagePullSecrets` para os Pods de sistema, com o Secret criado no namespace dos sistemas. Ao trocar imagens ou Secrets numa instalação existente, a reconciliação recria os Pods de sistema que ainda usam os valores anteriores;
   - host da rota do portal (`portalRoute.host`);
   - `auth.publicBaseUrl`;
   - `portal.webhookBaseUrl`;
   - e-mail do admin de emergência.

   Instale:

   ```bash
   helm install aidb-prod deploy/helm/appaiforge-portal -n aidb-prod -f values-production.yaml
   ```

O chart instala o Traefik junto (subchart, `traefik.enabled=true`), com os CRDs dele e os da Gateway API. Se o cluster já tem um Traefik, desligue o subchart; no modo de roteamento `gateway`, informe então o `Gateway` dele em `gateway.existing` (ver [Roteamento no Kubernetes](#7-roteamento-no-kubernetes)).

As migrações rodam num initContainer antes de cada subida do portal (`portal.migrateOnStart`). O chart recusa renderizar em produção com o admin de demonstração ligado ou sem o Secret externo. Os sistemas ficam no namespace da release. Para separá-los, defina `portal.systemsNamespace` com um namespace criado antes do `helm install` e só deste portal; a Role do portal é criada nele.

### 3. Primeiro acesso

Entre com o admin de emergência (ou pelo OIDC, se configurado) e crie os usuários. Não existe admin de demonstração em produção.

### 4. Primeiro sistema

1. Crie o sistema: em produção, o tipo é sempre "só implantação".
2. Na aba **Implantação**:
   - cadastre no GitLab a chave pública mostrada, como chave de implantação só leitura;
   - informe o repositório;
   - confirme a identidade do servidor.
3. A lista de versões mostra as tags do padrão (`v*` por padrão). **Implantar** coloca a versão no ar.

Com o modo automático e webhook, cadastre no projeto do GitLab o endereço e o segredo mostrados na aba, com o evento de tags ([GitLab, seção 7](gitlab.md#7-portal-de-produção-sistema-só-implantação)).

### 5. Atualizar o portal

1. Leia as notas da versão.
2. Aplique as migrações antes de reiniciar:
   - **Compose:** os comandos `build portal` e `run --rm ... alembic upgrade head` do passo 2a, depois `up -d --build`.
   - **Helm:** com `portal.migrateOnStart: true` (ligado no `values-production.yaml`), um initContainer roda `alembic upgrade head` com a imagem nova antes de o portal subir. O `helm upgrade` já basta.
3. Quando a versão mudar a imagem base, reconstrua-a (ou carregue-a no cluster). Os sistemas pegam a imagem nova quando são recriados.
4. **Helm, vindo de uma versão sem o Traefik no chart** (antes da change `gateway-api-traefik-subchart`): o `helm upgrade` não instala os CRDs de `crds/` (só o `helm install` faz isso), e sem eles o upgrade falha em `no matches for kind "GatewayClass"`. Aplique antes os da Gateway API (`kubectl apply --server-side -f deploy/helm/appaiforge-portal/crds/`) e, se o cluster ainda não tiver os do Traefik, os do chart dele (ver "CRDs ao atualizar o Traefik" na seção 7). Se o Traefik do cluster era um release à parte, os dois disputariam as mesmas portas. Escolha um caminho antes do `helm upgrade`:
   - desinstale o release antigo (`helm uninstall traefik -n traefik`) e deixe o chart instalar o dele. A entrada fica fora do ar até o Traefik novo ficar pronto;
   - ou mantenha o Traefik antigo com `traefik.enabled=false`. No modo `ingressroute` (padrão) não é preciso mais nada. No modo `gateway`, ligue antes o provider `kubernetesGateway` nesse Traefik, instale os CRDs da Gateway API, crie um `Gateway` nele e informe-o em `gateway.existing.name` e `gateway.existing.namespace`.

   O `helm upgrade` não muda o roteamento: o modo padrão continua sendo o de antes.

### 6. Backup

- Volume do Postgres do portal (`pgdata` no compose, PVC do StatefulSet no Helm).
- Diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

O código de cada sistema também está no GitLab, nas tags implantadas.

### 7. Roteamento no Kubernetes

As rotas `/apps/<slug>` e a do portal seguem `routing.mode` (change `gateway-api-traefik-subchart`, [ADR 0032](adr/0032-gateway-api-com-traefik-como-implementacao.md)): `ingressroute` (padrão desta versão, `IngressRoute` do Traefik) ou `gateway` (`HTTPRoute` da Gateway API). Os dois convivem só nesta versão; uma seguinte remove o `ingressroute`. Diferenças entre os modos no [README do chart](../deploy/helm/appaiforge-portal/README.md#roteamento).

**Trocar para `gateway`:**

```bash
helm upgrade aidb-prod deploy/helm/appaiforge-portal -n aidb-prod -f values-production.yaml \
  --set routing.mode=gateway
```

O portal reinicia com o modo novo e, logo depois de subir, a primeira passada da reconciliação republica a rota de todo sistema não arquivado (ativo ou em erro) pela Gateway API e apaga as `IngressRoute` deles, sem recriar os Pods. Um sistema em provisionamento ganha a rota nova ao terminar. Uma falha num sistema aparece no log do portal como "reconciliação do sistema <id> falhou" e é tentada de novo na passada seguinte. Confira abrindo `/apps/<slug>` de um sistema com e sem sessão: sem sessão, o login deve devolver à mesma página. Com TLS, o certificado sai da rota e vai para o listener HTTPS do `Gateway` do chart (`portalRoute.tlsSecretName`).

**Voltar para `ingressroute`:** o mesmo comando com `--set routing.mode=ingressroute`. A reconciliação logo depois da subida republica as rotas como `IngressRoute` e apaga os `HTTPRoute`.

**CRDs ao atualizar o Traefik.** O Helm instala os CRDs do chart (os do Traefik e os da Gateway API) só na primeira instalação e nunca os atualiza. Quando uma versão do portal trouxer outra versão do Traefik, aplique os CRDs novos antes do `helm upgrade`:

```bash
helm pull traefik/traefik --version <versão> --untar -d /tmp/traefik-chart
kubectl apply --server-side -f /tmp/traefik-chart/traefik/crds/
kubectl apply --server-side -f deploy/helm/appaiforge-portal/crds/
```

A versão dos CRDs da Gateway API que o chart traz está no nome do arquivo em `deploy/helm/appaiforge-portal/crds/`.

**Voltar a versão do portal** (`helm rollback`) para uma anterior ao Traefik no chart: a versão anterior não sabe apagar os `HTTPRoute`. Se o modo está em `gateway`, volte antes para `ingressroute` (`helm upgrade ... --set routing.mode=ingressroute`) e espere a reconciliação depois da subida: ela recria as `IngressRoute` dos sistemas e apaga os `HTTPRoute`. Só então rode o `helm rollback`. Ele remove o Traefik do chart; reinstale o release `traefik` à parte.
