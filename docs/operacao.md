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
- **Reconciliação**: no boot e periodicamente o portal recria containers ausentes (workspace persiste no bind).
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
   - imagem do portal (`image.repository` e `image.tag`) e imagem base dos sistemas (`portal.baseImage`). Com registro privado, use `imagePullSecrets` para o portal e anexe o Secret de pull ao `ServiceAccount` `default` do namespace dos sistemas: os Pods de sistema usam esse ServiceAccount;
   - host da rota do portal (`portalRoute.host`);
   - `auth.publicBaseUrl`;
   - `portal.webhookBaseUrl`;
   - e-mail do admin de emergência.

   Instale:

   ```bash
   helm install aidb-prod deploy/helm/appaiforge-portal -n aidb-prod -f values-production.yaml
   ```

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

### 6. Backup

- Volume do Postgres do portal (`pgdata` no compose, PVC do StatefulSet no Helm).
- Diretório de workspaces (`APPAIFORGE_WORKSPACES_DIR`).

O código de cada sistema também está no GitLab, nas tags implantadas.

