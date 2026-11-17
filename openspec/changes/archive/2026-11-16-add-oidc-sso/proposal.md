# Proposal

## Why

Em ambiente corporativo, usuários, grupos e papéis vivem num diretório (LDAP) federado
por um IdP (Keycloak) e são concedidos por um processo externo de solicitação e
aprovação de acesso — não pelo admin do portal. Hoje o portal só sabe autenticar por
e-mail e senha locais e mantém usuários e grupos na própria base, o que obriga a
duplicar a gestão de identidade e impede SSO.

Além disso, o acesso às apps geradas tem duas falhas que o SSO tornaria visíveis:
quem abre o link de uma app sem estar logado cai na raiz do portal e, depois do login,
não volta para a app; e a app guarda uma sessão própria após o handoff `/entry`, então
o logout do portal (ou a perda de acesso) não alcança quem já está dentro dela.

## What Changes

- Novo modo de autenticação escolhido por ENV (`APPAIFORGE_AUTH_MODE` = `local` |
  `oidc`), fixado na instalação: o portal registra o modo no primeiro boot e se recusa
  a subir se a ENV divergir depois. Trocar de modo não é suportado.
- **Modo `oidc`**: login SSO via OpenID Connect (authorization code com PKCE) contra um
  IdP externo; o portal redireciona ao IdP e recebe o usuário de volta autenticado.
  Papel global (`admin`/`editor`/`app_user`) e grupos vêm dos claims do token; usuário
  sem papel reconhecido é recusado. O usuário local passa a ser um registro-sombra
  criado no primeiro login e atualizado a cada login, identificado pelo `sub` do IdP.
  Perda de papel ou desativação no IdP passa a valer no próximo refresh da sessão.
  Logout encerra também a sessão no IdP.
- **Modo `local`**: comportamento atual preservado (login e-mail/senha, CRUD de
  usuários e de membros de grupo pelo admin).
- Grupos continuam cadastrados pelo admin no portal nos dois modos e vinculados a
  sistemas no portal. No modo `oidc`, o nome do grupo cadastrado casa exatamente com o
  nome que chega no claim de grupos; a pertença vem do token, não do banco.
  **BREAKING (modo oidc)**: criação/edição/exclusão de usuários e gestão de membros
  pelo admin deixam de existir nesse modo.
- Admin **break-glass**: um administrador local definido por ENV, que entra por uma
  rota de login local disponível nos dois modos, sempre com tipo `admin`, sessão curta,
  rate limit, auditoria de cada login e aviso visual de sessão de emergência.
- **BREAKING**: o acesso a `/apps/{slug}` passa a ser verificado pelo edge a cada
  requisição, contra a sessão do portal. Sem sessão → login com retorno ao endereço da
  app; sem acesso → recusa; com acesso → a app recebe a identidade do usuário (papel e
  grupos) num JWT assinado e restrito àquela app, a cada requisição. Isso substitui o
  handoff `/entry` + `?t=` e a sessão própria da app como mecanismo de identidade (o ADR
  0006 é substituído). O handoff legado continua disponível pelo botão "Abrir app" para
  que apps já geradas sigam funcionando; o link direto só funciona em apps regeneradas.
- Keycloak local no stack E2E, com realm importado (client do portal, papéis, grupos,
  mapper de grupos e usuários de teste), para exercitar o fluxo completo.

## Capabilities

### New Capabilities
- `oidc-authentication`: login SSO por OpenID Connect contra IdP externo — fluxo de
  redirecionamento e retorno, mapeamento de claims para papel e grupos, provisionamento
  do usuário-sombra, manutenção e revogação da sessão pelo IdP e logout federado.

### Modified Capabilities
- `portal-identity`: autenticação passa a depender do modo configurado (local ou
  OIDC) com trava de modo; nova requirement de admin break-glass; login passa a
  retornar ao destino pedido; tipos globais e pertença a grupos vêm do token no modo
  OIDC; administração de usuários e gestão de membros ficam restritas ao modo local;
  grupos no modo OIDC casam pelo nome com o claim.
- `app-serving`: acesso a `/apps/{slug}` verificado a cada requisição pelo portal, com
  redirecionamento ao login e retorno à app; propagação de identidade passa a ser um
  JWT por app com papel e grupos, entregue a cada requisição, e a revogação/logout
  no portal alcança a app imediatamente.

## Impact

- **Código do portal**: `auth.py`, `security.py`, `main.py` (rota `/entry`, seed do admin,
  novas rotas de login/callback/logout e endpoint de verificação do edge), `rbac.py`,
  `services/directory.py`, `ui/login.py`, `ui/admin.py`, `ui/common.py`,
  `ui/system_detail.py`, `config.py`, `models.py` + migração Alembic (`users`, `sessions`,
  trava de modo, grupos vistos em tokens).
- **Edge**: `edge.py` (driver Docker) e `drivers/kubernetes_driver.py` (IngressRoute)
  ganham o middleware de verificação de acesso na rota de cada app.
- **Apps geradas**: `app_template/identity.py`, `guidelines.py`, placeholder do
  `base-image/afsupervisor/supervisor.py` e app de exemplo do `harness/fake.py` passam a
  ler a identidade por requisição.
- **Dependências**: biblioteca cliente OIDC/JWT no portal.
- **Deploy/testes**: serviço Keycloak + realm em `deploy/docker-compose.e2e.yml`; novos
  valores de OIDC/break-glass no `docker-compose.yml` e no chart Helm; testes E2E que
  usam `/entry/{slug}` migram para `/apps/{slug}`.
- **Docs**: novo ADR substituindo o 0006; README com configuração dos modos.
