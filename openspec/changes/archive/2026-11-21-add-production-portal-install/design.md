# Design

## Context

- **Como o driver Docker acha os containers.** Ele acha cada container pelo nome: `appaiforge-sys-<slug>` para o sistema e nomes derivados do slug para os sidecars dbgate e https-proxy.
  - `provision` remove à força o que houver com esses nomes antes de criar.
  - `remove` (arquivar ou excluir) também remove à força pelo nome.
  - `reconcile_one` adota o container que encontrar com o nome.
  - Os rótulos atuais são `appaiforge.system_id`, `appaiforge.slug` e `appaiforge.managed`. Nenhum diz a qual instalação o container pertence.
- **Registro da instalação.** A tabela `portal_instance` (linha única, id 1) já existe e guarda o modo de autenticação fixado no primeiro boot. Quem a escreve é `auth_mode.enforce_mode_lock`, chamado por `check_on_boot` em `main.py` antes de qualquer seed.
- **Chart Helm** (`deploy/helm/appaiforge-portal`):
  - Já passa `APPAIFORGE_PORTAL_INTERNAL_URL` com o DNS do próprio Service e tem `extraEnv`.
  - Não tem valor para `INSTALLATION_ROLE`, `WEBHOOK_BASE_URL` nem `DEPLOY_*`.
  - Não cria rota para o portal: o acesso é por `port-forward`.
  - Os sistemas usam `IngressRoute` do Traefik com `PathPrefix(/apps/<slug>)`, sem host.
- **Compose.** `deploy/docker-compose.yml` é o compose de desenvolvimento completo, com LiteLLM, broker, MySQL de demonstração, observabilidade e admin de demonstração. O único portal de produção pronto está na stack E2E com GitLab, que roda homologação e produção no mesmo host Docker.
- Decisão do usuário: produção roda num host Docker próprio. Dois portais no mesmo host não são suportados fora de testes.

## Goals / Non-Goals

**Goals:**

- Instalar um portal de produção a partir de um arquivo pronto, por compose ou por Helm, sem copiar a stack E2E.
- Um portal nunca remove, para ou adota um container de outra instalação, mesmo por engano de configuração.
- Um portal de produção num host compartilhado falha cedo, com mensagem clara, em vez de corromper sistemas.
- O chart com valores padrão e o compose de desenvolvimento continuam produzindo o mesmo resultado.

**Non-Goals:**

- Suportar produção e homologação no mesmo host Docker (prefixo de nome por instalação).
- Rótulo de instalação nos Pods do driver Kubernetes. O isolamento lá é um namespace por portal (o da release), exigido no guia.
- TLS, DNS e certificados: são do controlador de entrada e do operador. O guia só aponta onde configurar.
- Migração de schema do banco de produção.

## Decisions

### D1: Identificador da instalação em `portal_instance`

- Nova coluna `installation_id` (texto, 32 hex), preenchida com `secrets.token_hex(16)` na criação da linha.
- Uma linha existente sem valor recebe um na primeira subida desta versão. A migração cria a coluna anulável e o boot completa.
- A gravação fica no mesmo passo de boot que já cria a linha (`enforce_mode_lock`), antes de qualquer seed ou reconciliação.
- Leitura por `installation_id()`, com cache no processo (não muda durante a vida do portal).
- Alternativa descartada: um valor em configuração (env). Ele seria copiado entre instalações junto com os arquivos de configuração, que é justamente o erro a evitar. O banco é o que distingue uma instalação da outra.

### D2: Rótulo nos containers e dono de um container

- Os três containers de um sistema (sistema, dbgate, https-proxy) ganham o rótulo `appaiforge.installation=<id>`, além dos que já têm.
- Uma função única decide se um container existente é "deste portal para este sistema":
  - **Com rótulo de instalação:** é deste portal se o rótulo é o desta instalação e `appaiforge.system_id` é o do sistema.
  - **Sem rótulo de instalação** (anterior a esta versão): é deste portal se `appaiforge.system_id` é o do sistema.
  - **Sem `appaiforge.managed`:** é um container que o portal não criou e nunca é deste portal.
- `provision`, `remove`, `reconcile_one` e a recriação dos sidecars passam por essa função antes de remover ou adotar qualquer container pelo nome.
- Se o container é de outro dono, o driver levanta `ComputeUnitOwnedElsewhere` com o nome e o dono encontrado.
- O provisionamento põe o sistema em `error` com a mensagem e não toca no container. A reconciliação faz o mesmo e segue para o próximo sistema.
- Rótulos de containers antigos não podem ser trocados com o container rodando. Eles ganham o rótulo de instalação na próxima recriação normal, e até lá a regra "sem rótulo" vale.

### D3: Checagem do host no boot de produção

- Em `main.py`, logo depois de `check_on_boot`, roda `check_docker_host()`, só com driver Docker e papel `production`.
- Ela lista os containers com `appaiforge.managed=true` e separa os que não são desta instalação:
  - rótulo de instalação diferente;
  - ou sem rótulo e com `appaiforge.system_id` que não existe no banco.
- Se houver algum, o portal levanta erro e não sobe. A mensagem lista até dez nomes e diz que produção precisa de host Docker próprio.
- Exceção: `APPAIFORGE_ALLOW_SHARED_DOCKER_HOST=true` só registra aviso. Fica documentada como "só para a stack de testes" e é ligada no `portal-prod` de `docker-compose.e2e-gitlab.yml`.
- Portal de desenvolvimento não faz essa checagem: a proteção dele é a D2.
- Alternativa descartada: só a D2, sem checagem no boot. Ela protege os containers, mas o sistema de produção ficaria em erro só quando um slug coincidisse, talvez semanas depois. A checagem no boot falha na instalação, que é quando o operador pode trocar de host.

### D4: Valores e guardas do chart

- **Valores novos:**
  - `portal.installationRole` (`development`)
  - `portal.webhookBaseUrl` (`""`)
  - `portal.deploy.pollInterval` (60), `portal.deploy.healthTimeout` (90), `portal.deploy.healthInterval` (2)
- Cada valor vira a env correspondente. As de implantação só entram quando o papel é `production`, para que o resultado padrão não mude.
- **Guardas** com `fail` no template, quando o papel é `production`:
  - `portal.seedDemoAdmin` precisa ser `false`;
  - `secrets.existingSecret` não pode ser vazio.
- Novo `values-production.yaml` de exemplo:
  - papel `production`;
  - `seedDemoAdmin: false`;
  - `existingSecret`;
  - break-glass;
  - `publicBaseUrl`;
  - `webhookBaseUrl`;
  - rota do portal ligada;
  - sistemas no namespace da release, que é só deste portal. A RBAC do chart só concede permissão nesse namespace, então um `systemsNamespace` diferente não é usado.

### D4b: Endereço interno do portal com o nome completo do Service

- Achado ao instalar no kind: o chart passava `APPAIFORGE_PORTAL_INTERNAL_URL=http://<nome>:8080`. O forwardAuth das rotas `/apps/<slug>` é chamado pelo Traefik, que roda no seu próprio namespace, onde esse nome curto não resolve. Toda app de sistema criada pelo driver Kubernetes respondia 500.
- O chart passa a usar `http://<nome>.<namespace>.svc.cluster.local:<porta>`, que resolve de qualquer namespace e continua valendo para os sidecars.
- É a única linha que muda na renderização padrão do chart.

### D4c: Migrações antes de subir, no chart

- Ao escrever o guia de atualização: o portal novo depende das colunas que a migração cria (nesta versão, `installation_id`), e rodar `alembic` com `exec` no pod antigo usaria as migrações antigas.
- Novo valor `portal.migrateOnStart` (padrão `false`): um initContainer com a imagem nova roda `alembic upgrade head` antes do portal. Se o Postgres ainda não estiver pronto, ele falha e o Kubernetes tenta de novo.
- Fica desligado por padrão porque bancos criados antes sem Alembic (só `create_all`) fariam as migrações tentarem recriar as tabelas. O `values-production.yaml` liga, já que a instalação de produção é nova.

### D5: Rota do portal no chart

- Nova `templates/ingressroute.yaml`, criada só com `portalRoute.enabled: true`. Valores:
  - `portalRoute.host`: obrigatório quando ligada;
  - `portalRoute.entryPoints`: padrão `[web]`;
  - `portalRoute.tlsSecretName`: opcional, vira `tls.secretName`.
- Match `Host(<host>) && PathPrefix(/)` com `priority: 1`.
- As rotas `/apps/<slug>` do driver têm prioridade calculada pelo Traefik (comprimento da regra), sempre maior que 1. Elas continuam ganhando.
- A RBAC do chart não muda: a rota é criada pelo Helm, não pelo portal.
- Alternativa descartada: um `Ingress` padrão do Kubernetes. O cluster já depende do Traefik e de seus CRDs para os sistemas, e misturar dois tipos de rota complica a prioridade.

### D6: Compose de produção

- Novo `deploy/docker-compose.production.yml`, com nome de projeto `aidb-prod`.
- **Serviços:**
  - `postgres`: senha `${APPAIFORGE_POSTGRES_PASSWORD:?…}`.
  - `traefik`: porta `${APPAIFORGE_HTTP_PORT:-80}`, mesmo `traefik.yml`.
  - `portal`:
    - `APPAIFORGE_INSTALLATION_ROLE=production`;
    - `APPAIFORGE_SECRET_KEY=${APPAIFORGE_SECRET_KEY:?…}`;
    - `APPAIFORGE_SEED_DEMO_ADMIN=0`;
    - `APPAIFORGE_INFERENCE_BROKER_ENABLED=false`;
    - break-glass, OIDC, `PUBLIC_BASE_URL`, `WEBHOOK_BASE_URL` e `DEPLOY_*` por variável.
  - Mesmos volumes nomeados e bind de workspaces e configs do compose de desenvolvimento.
- **Sem** LiteLLM, broker, MySQL nem observabilidade. Para observabilidade, o guia aponta o compose de desenvolvimento como referência.
- `deploy/production.env.example` lista as variáveis com comentários. O `.env` real nunca é versionado.
- O `harness_mode` não importa num portal sem agente e fica no padrão.

### D7: Guia em `docs/operacao.md`

Seção "Instalar um portal de produção":

1. Pré-requisitos: host próprio ou namespace próprio, GitLab alcançável e, para o webhook, o GitLab alcançando o portal.
2. Instalação por compose.
3. Instalação por Helm.
4. Primeiro acesso pelo break-glass ou OIDC.
5. Primeiro sistema só implantação: chave só leitura no GitLab, host confirmado, tag.
6. Webhook.
7. Atualização: `alembic upgrade head` antes de reiniciar e reconstrução da imagem base.
8. Backup.

Os detalhes de GitLab continuam em `docs/gitlab.md`, seção 7, com link. Um ADR curto registra a D2 e a D3.

## Risks / Trade-offs

- **[Container órfão do próprio portal bloqueia a produção]** Um container gerenciado deixado por uma exclusão interrompida, com `system_id` que já não existe no banco, conta como de outra instalação quando não tem rótulo. → A mensagem diz como conferir (`docker inspect`) e remover. Containers criados a partir desta versão têm rótulo e não caem nesse caso.
- **[Exceção ligada em produção por engano]** → O nome deixa claro o que ela faz, o boot registra aviso a cada subida, e o guia e a `configuracao.md` dizem que é só para testes.
- **[Mudança no caminho de remoção]** `remove`, `provision` e `reconcile_one` estão no caminho de todo sistema. → A regra "sem rótulo + mesmo system_id = deste portal" mantém os sistemas atuais funcionando sem recriar. A integração Docker existente roda inteira, mais os casos novos.
- **[Chart sem teste em cluster gerenciado real]** O chart continua validado só no kind. → O README do chart já diz isso. O guia repete.
- **[Prioridade da rota do portal]** Depende do cálculo de prioridade do Traefik v3. → Teste no kind: com a rota do portal ligada, `/apps/<slug>` continua indo para a app.

## Migration Plan

1. Migração Alembic: coluna `portal_instance.installation_id`, anulável. O boot preenche quando está vazia.
2. Portais existentes sobem normalmente. Os containers atuais continuam reconhecidos pela regra "sem rótulo" e ganham o rótulo na próxima recriação.
3. Stack E2E com GitLab: `APPAIFORGE_ALLOW_SHARED_DOCKER_HOST=true` no `portal-prod`.
4. Reversão: a versão anterior ignora a coluna e o rótulo novos.
