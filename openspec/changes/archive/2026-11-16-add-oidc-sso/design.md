# Design

## Context

Estado atual relevante (motivação em `proposal.md`):

- **Login local** em `ui/login.py` → `auth.authenticate()` cria `sessions(id=sha256(token))`; o cookie
  `appaiforge_session` é gravado via `ui.run_javascript` (sem HttpOnly), porque handlers do
  NiceGUI não devolvem `Response`.
- **Handoff para a app**: `GET /entry/{slug}` (em `main.py`) valida sessão + `can_access_system`
  e redireciona para `/apps/{slug}/?t=<HMAC>` assinado com `systems.identity_secret` (TTL 60s,
  ADR 0006). A app troca `?t=` por sessão própria (`app_template/identity.py`); o placeholder do
  `afsupervisor` e a app de exemplo do `harness/fake.py` validam `?t=` em cada GET.
- **Edge**: `/apps/{slug}` vai direto ao container pelo Traefik, sem autenticação — file provider
  (`edge.publish_app_docker`, `apps-{slug}.yml`) no driver Docker e `IngressRoute` +
  `Middleware stripPrefix` no driver Kubernetes. O portal roda dentro do cluster sob o driver
  Kubernetes (change `deploy-portal-in-cluster`) e é alcançável por `portal_internal_url`.
- **RBAC** (`rbac.py`): `visible_system_ids(user)` = dono ∪ sistemas de grupos via
  `group_members`; admin vê tudo. Recebe um `User` ORM.
- **E2E**: stack dedicado `deploy/docker-compose.e2e.yml` (porta 8081), login via formulário com
  `APPAIFORGE_SEED_DEMO_ADMIN=1`; vários testes usam `/entry/{slug}`. Contêineres de sistema têm
  nome global `{SYSTEM_CONTAINER_PREFIX}-{slug}`.

## Goals / Non-Goals

**Goals:**
- Um único conceito de "quem está nesta requisição" (`Principal`) usado por portal, RBAC e edge,
  independente do modo de autenticação.
- A app nunca recebe o token bruto do IdP nem o cookie de sessão como fonte de identidade.
- Fluxo OIDC exercitado ponta a ponta no E2E com Keycloak real.

**Non-Goals:**
- Keycloak no chart Helm ou no `docker-compose.yml` de produção (o IdP é externo).
- Admin API do Keycloak, criação de grupos no IdP, LDAP no E2E.
- Back-channel logout iniciado pelo IdP (a revogação chega pela revalidação periódica).
- Isolar o cookie do portal das apps (ver Riscos) — fica para change futura.
- Remover o handoff legado `?t=` (mantido como compatibilidade; ver D9).

## Decisions

### D1. Modo de autenticação e trava na base

`APPAIFORGE_AUTH_MODE` (`local` default | `oidc`). Nova tabela `portal_instance` (linha única)
com `auth_mode`. No startup: sem linha → grava o modo configurado; com linha divergente → aborta o
boot com mensagem explícita. A migração Alembic que cria a tabela grava `local` quando a base já
tem usuários (instalação existente era, por definição, local) e deixa vazia numa base nova.
Validação de configuração do modo `oidc` (emissor, client id/secret, URL pública do portal) também
aborta o boot.

*Alternativa*: só documentar "não troque". Rejeitada — a troca silenciosa deixa donos órfãos e
usuários duplicados sem nenhum sinal.

### D2. Cliente OIDC: Authlib, estado da tentativa em cookie cifrado

Usar `authlib` (cliente OAuth2/OIDC + validação de JWT/JWKS) com `httpx`, já dependência do
portal. Rotas FastAPI (não páginas NiceGUI, para poder devolver `Set-Cookie` HttpOnly):

- `GET /auth/login?next=` → gera `state`, `nonce`, `code_verifier` (PKCE S256), guarda-os junto
  com `next` num cookie `aidb_oidc_attempt` cifrado com o Fernet existente (`security._fernet`),
  HttpOnly, SameSite=Lax, path `/auth`, validade 10 min; redireciona ao `authorization_endpoint`.
- `GET /auth/callback` → valida `state` contra o cookie, troca `code` por tokens, valida ID token
  (assinatura via JWKS, `iss`, `aud`, `nonce`, `exp`), mapeia claims (D4), cria sessão, apaga o
  cookie da tentativa e redireciona para `next` saneado.
- `GET /auth/logout` → apaga sessão local e redireciona ao `end_session_endpoint` com
  `id_token_hint` e `post_logout_redirect_uri`.

Configuração: `oidc_issuer`, `oidc_client_id`, `oidc_client_secret`, `oidc_scopes`
(`openid email profile`), `oidc_roles_claim` (`realm_access.roles`), `oidc_groups_claim`
(`groups`), `oidc_internal_base_url` (opcional, D11), `public_base_url`.

*Alternativas*: implementar à mão com `httpx` + `joserfc` (mais código de segurança sob nossa
responsabilidade); integração Starlette do Authlib (exige `SessionMiddleware` próprio, que
conflita com o storage do NiceGUI). Guardar a tentativa numa tabela também funcionaria, mas o
cookie cifrado evita limpeza de linhas órfãs.

### D3. Sessão: cookie HttpOnly e snapshot de identidade

`sessions` ganha: `auth_method` (`local` | `oidc` | `break_glass`), `user_type` e `groups` (snapshot
JSON usado no modo oidc), `refresh_token_enc` e `id_token_enc` (Fernet), `revalidate_at`.
Todo login (inclusive local) passa a ser concluído por rota FastAPI que devolve `Set-Cookie`
HttpOnly, SameSite=Lax: o formulário local faz POST para `/auth/local` em vez de setar o cookie
por JS. SameSite=Lax é necessário para o cookie acompanhar a navegação de volta do IdP.

`auth.resolve_principal(token) -> Principal | None` substitui `resolve_user` como ponto único:
`Principal(user_id, email, type, group_names, auth_method, break_glass)`. Modo local: tipo e
grupos lidos do banco (`users.type`, `group_members`). Modo oidc: do snapshot da sessão.

### D4. Mapeamento de claims e usuário-sombra

- Papéis: lê `oidc_roles_claim` (caminho com ponto) do **access token** decodificado e validado
  (Keycloak põe `realm_access.roles` lá); maior de `admin` > `editor` > `app_user`; nenhum → login
  recusado com página "acesso não concedido".
- Grupos: `oidc_groups_claim`; lista de nomes. Casamento exato com `groups.name` no momento do uso
  (RBAC), não no login — cadastrar um grupo passa a valer sem novo login.
- `users` ganha `idp_subject` (único, nulo no modo local), `break_glass` (bool),
  `last_login_at`; `password_hash` passa a aceitar nulo. Upsert pelo `sub`; atualiza e-mail e
  `type` (o `type` persistido serve para listagens e para o histórico; a autorização usa o
  snapshot da sessão). Conflito de e-mail com outro usuário → login recusado e registrado.
- Nova tabela `observed_idp_groups(name, last_seen_at)` atualizada a cada login/refresh,
  alimentando as sugestões da tela de grupos.

### D5. Revalidação lazy com refresh token

Ao resolver uma sessão oidc com `revalidate_at` vencido, o portal faz `refresh_token` grant
dentro de `SELECT … FOR UPDATE` na linha da sessão (Keycloak pode rotacionar refresh tokens;
duas requisições simultâneas não podem gastar o mesmo). Sucesso → atualiza snapshot, tokens e
`revalidate_at = agora + oidc_revalidate_seconds` (default 300). Falha `invalid_grant` → apaga a
sessão. Falha de rede com o IdP → mantém a sessão até `revalidate_at + 60s` de tolerância e depois
a encerra (fail-closed). O realm do E2E usa access token de 5 min.

*Alternativa*: job periódico revalidando todas as sessões — mais carga e sem ganho, já que só
importa o estado no momento do uso.

### D6. RBAC sobre `Principal`

`visible_system_ids` e `can_access_system` passam a receber `Principal`. Pertença:
modo local → `group_members`; modo oidc → `groups.name IN principal.group_names`. A UI de admin
recebe o modo para esconder criação/edição/desativação/exclusão de usuários e a gestão de
membros, e mostrar o aviso ao renomear. Os chamadores de `get_current_user` nas páginas passam a
obter o `Principal` (o `User` ORM continua disponível para dados de perfil como tema).

### D7. Break-glass

ENV `APPAIFORGE_BREAKGLASS_EMAIL` + `APPAIFORGE_BREAKGLASS_PASSWORD_HASH` (formato scrypt já usado
por `security.hash_password`; novo comando `appaiforge hash-password` na CLI). No startup:
presente → upsert do usuário com `break_glass=true`, `type=admin`, `active=true`; ausente →
qualquer usuário `break_glass` existente é desativado e suas sessões apagadas. Login em
`/login/local` (formulário) → `POST /auth/local`; no modo oidc só aceita o usuário break-glass.
Sessão com expiração de 8 h. Rate limit em memória por (IP, e-mail): 5 falhas em 15 min bloqueiam
por 15 min — o portal roda em réplica única nos dois drivers. Auditoria via `ManagementAudit`
(`resource=session`, `action=breakglass_login`/`breakglass_login_failed`). Banner no layout
comum quando `principal.break_glass`. Ações de admin sobre um usuário `break_glass` são
recusadas no serviço (não só escondidas na UI).

`APPAIFORGE_SEED_DEMO_ADMIN` continua existindo para o stack local de desenvolvimento.

### D8. Edge: forwardAuth em `/apps/*`

Endpoint interno `GET /internal/edge/auth/{slug}`, chamado pelo Traefik com os headers originais
(inclui `Cookie`) e `X-Forwarded-Uri`:

```
sem sessao valida  -> 302 /login?next=<X-Forwarded-Uri saneado>
sem acesso         -> 403 (pagina curta "sem permissao")
ok                 -> 200 + X-AIDB-Identity: <JWT da app (D9)>
```

- Driver Docker: `apps-{slug}.yml` ganha middleware `app-{slug}-auth`
  (`forwardAuth.address = {portal_internal_url}/internal/edge/auth/{slug}`,
  `authResponseHeaders: [X-AIDB-Identity]`) **antes** do `stripPrefix`.
- Driver Kubernetes: `Middleware` CRD `{name}-auth` equivalente, referenciado no `IngressRoute`
  antes do strip; endereço pelo DNS do Service do portal (`portal_internal_url`).
- `authResponseHeaders` sobrescreve o header vindo do cliente; como o 200 sempre inclui
  `X-AIDB-Identity`, um valor forjado nunca passa. Teste E2E cobre esse caso.
- Sem cache: cada requisição consulta sessão + acesso (as duas consultas são por chave/índice).
  É o que dá "logout e revogação na requisição seguinte".
- `/login?next=` passa a aceitar `next` (modo local → formulário; modo oidc → `/auth/login`).
  Saneamento de `next`: só caminho relativo começando com `/` e sem `//` nem `\`.

*Alternativas*: middleware na própria app (depende de código gerado pelo agente para segurança);
cookie por app emitido no `/entry` (logout não propaga, link direto sem sessão continua quebrado).

### D9. Identidade da app: JWT HS256 por sistema, por requisição

`X-AIDB-Identity` é um JWT HS256 assinado com `systems.identity_secret` (já distribuído como
`APP_IDENTITY_SECRET`), com `iss=aidb-portal`, `aud=aidb-app:{slug}`, `sub`, `email`,
`user_type`, `groups` (nomes de grupos cadastrados do usuário), `exp` = 60 s. Segredo por sistema +
`aud` impedem que a identidade de uma app valha em outra; a app nunca vê o token do IdP.

`app_template/identity.py` passa a expor `current_identity(request)` (valida header a cada
requisição, só stdlib — a base image não ganha dependência) e um middleware que responde 401
quando ausente/inválido. Guidelines atualizadas; placeholder do `afsupervisor` e app do
`harness/fake.py` passam a ler o header.

Compatibilidade: `/entry/{slug}` continua existindo e passa a redirecionar para
`/apps/{slug}/?t=<HMAC legado>`, para que apps já geradas (que só conhecem `?t=`) sigam
funcionando a partir do botão "Abrir app"; apps novas ignoram `?t=`. Acesso direto pelo link a uma
app antiga mostra a mensagem "abra pelo portal" dela até ser regenerada. A remoção do legado fica
para change futura.

*Alternativas*: RS256 com JWKS do portal (exige distribuição de chave pública e não acrescenta
isolamento entre apps); repassar o access token do IdP (dá à app gerada um token reutilizável
contra o portal e outras apps).

### D10. UI

- `/login`: modo local → formulário atual (agora POST); modo oidc → botão "Entrar com SSO"
  e redirecionamento automático para `/auth/login` quando chega com `next`.
- `/login/local`: formulário só e-mail/senha, sem link a partir das páginas no modo oidc.
- Admin › Usuários: modo oidc → tabela somente leitura (e-mail, tipo, último login).
- Admin › Grupos: modo oidc → sem gestão de membros; diálogo de criar grupo com sugestões de
  `observed_idp_groups` não cadastrados e aviso para nome nunca visto; aviso ao renomear.
- "Abrir app" em `system_detail.py` mantém `/entry/{slug}` (D9).

### D11. Keycloak no E2E e emissor público × interno

Novo stack `deploy/docker-compose.e2e-oidc.yml` (projeto `appaiforge-e2e-oidc`, edge na porta
8082, Keycloak na 8180) com portal em `APPAIFORGE_AUTH_MODE=oidc`, base própria e break-glass
configurado. Um stack separado é necessário porque o modo é travado por base. Os dois stacks
**não** rodam ao mesmo tempo (nomes de contêiner de sistema são globais); documentado no conftest.

Keycloak `quay.io/keycloak/keycloak` (versão fixada) em `start-dev --import-realm` com
`deploy/keycloak/aidb-realm.json`: client confidencial `aidb-portal` (standard flow, PKCE S256,
redirect `http://localhost:8082/auth/callback`, post-logout redirect), realm roles `admin`,
`editor`, `app_user`, grupos `e2e-financeiro` e `e2e-vendas`, mapper de grupos sem caminho
completo no ID/access token, access token de 5 min e usuários de teste (um por papel, um sem
papel, um com grupo).

O navegador precisa do Keycloak em `localhost:8180` e o portal em `keycloak:8080`. Keycloak com
`KC_HOSTNAME=http://localhost:8180` e `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` mantém o `iss`
público; o portal valida `iss` contra `oidc_issuer` (público) e, quando `oidc_internal_base_url`
está definido, reescreve só os endpoints servidor-a-servidor (discovery, token, JWKS) para a base
interna. `authorization_endpoint` e `end_session_endpoint` continuam públicos.

Testes em `portal/tests/e2e_oidc/` com conftest próprio.

### D12. Deploy e documentação

- `docker-compose.yml` e chart Helm: novas variáveis (modo, OIDC, break-glass) com segredos no
  Secret existente (`oidcClientSecret`, `breakglassPasswordHash`); default `local`.
- Novo ADR `0027` (SSO OIDC, `Principal` e identidade das apps por forwardAuth) substituindo o
  0006 e emendando o 0014 (autenticação deixa de ser só local). README com a configuração dos dois
  modos e do break-glass.

## Risks / Trade-offs

- [O cookie de sessão do portal é enviado às apps, que ficam na mesma origem] → já acontece
  hoje; HttpOnly impede leitura por JS, mas o servidor da app recebe o header `Cookie`. Mitigação
  futura (apps em subdomínio ou remoção do cookie no edge) registrada como não-meta.
- [forwardAuth adiciona uma ida ao portal por requisição de app, incluindo assets] → consultas
  indexadas; se virar gargalo, cache curto com invalidação por logout fica como evolução,
  ciente de que relaxa o "na requisição seguinte".
- [Portal fora do ar derruba o acesso a todas as apps] → aceito: fail-closed é o comportamento
  desejado para autorização.
- [Revogação no IdP leva até 5 min] → limite explícito na spec; access token curto no realm.
- [Rotação de refresh token com requisições concorrentes] → lock de linha na revalidação (D5).
- [Rate limit em memória perde estado no restart e não escala horizontalmente] → portal é réplica
  única; documentado.
- [Renomear grupo no modo oidc corta acesso] → aviso na UI (spec) e auditoria do rename.
- [Apps antigas não aceitam link direto] → compatibilidade pelo `/entry` (D9); regeneração resolve.
- [Traefik com `hostNetwork` (kind) não resolve o Service do portal chamado pelo forwardAuth, e as
  apps respondem 500] → `deployment.dnsPolicy: ClusterFirstWithHostNet` no `traefik-values.yaml`
  (achado na implementação), documentado em `docs/driver-kubernetes.md`.
- [Divergência de emissor entre navegador e portal no E2E/compose] → D11; erro de `iss` é
  registrado com o valor recebido e o esperado para diagnóstico.

## Migration Plan

1. Migração Alembic: colunas novas em `users` e `sessions`, `password_hash` nulo, tabelas
   `portal_instance` e `observed_idp_groups`; grava `auth_mode=local` se já houver usuários.
   Sessões existentes continuam válidas como `auth_method=local`.
2. Deploy do portal: rotas Traefik/IngressRoute das apps são regravadas com forwardAuth na
   reconciliação de startup (`publish` já é idempotente).
3. Instalações novas que querem SSO sobem com `APPAIFORGE_AUTH_MODE=oidc` desde o primeiro boot.
4. Rollback: downgrade da migração e versão anterior do portal; as rotas voltam a ser escritas sem
   forwardAuth no próximo startup. Uma instalação oidc não tem caminho de volta para local.
