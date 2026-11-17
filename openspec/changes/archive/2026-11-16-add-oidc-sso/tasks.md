# Tasks

## 1. Base de dados, configuração e trava de modo

- [x] 1.1 Adicionar em `config.py` as configurações `auth_mode`, `public_base_url`, `oidc_*` (issuer, client id/secret, scopes, roles/groups claim, internal base url, revalidate seconds) e `breakglass_email`/`breakglass_password_hash`; verificar com teste unitário dos defaults (`auth_mode=local`)
- [x] 1.2 Adicionar `authlib` às dependências do portal (`pyproject.toml` + `uv.lock`) e verificar que `uv sync` e o build de `deploy/portal.Dockerfile` passam
- [x] 1.3 Estender `models.py` (`users.idp_subject` único, `break_glass`, `last_login_at`, `password_hash` nulo; `sessions.auth_method`, `user_type`, `groups`, `refresh_token_enc`, `id_token_enc`, `revalidate_at`; tabelas `portal_instance` e `observed_idp_groups`) e criar a migração Alembic que grava `auth_mode=local` quando já há usuários; verificar `alembic upgrade head`/`downgrade -1` numa base com dados
- [x] 1.4 Implementar a trava de modo e a validação de configuração OIDC no startup (D1); verificar com testes unitários: primeiro boot grava o modo, modo divergente aborta, configuração oidc incompleta aborta com a chave faltante

## 2. Principal, sessão e login local por rota HTTP

- [x] 2.1 Introduzir `Principal` e `auth.resolve_principal()` lendo tipo/grupos do banco no modo local e do snapshot no oidc (D3); verificar com testes unitários dos dois modos
- [x] 2.2 Criar `POST /auth/local` (devolve `Set-Cookie` HttpOnly, SameSite=Lax) e trocar o formulário de `/login` para usá-lo, com suporte a `next` saneado; verificar com testes de integração (cookie HttpOnly, `next` relativo aceito, `//evil` e URL absoluta ignorados) e com o E2E de login existente
- [x] 2.3 Migrar `rbac.py` (`visible_system_ids`, `can_access_system`) e os chamadores de `get_current_user` para `Principal` (D6), rodando `impact` do GitNexus antes de editar; verificar com os testes unitários/BDD de RBAC e `portal-identity` existentes passando
- [x] 2.4 Fazer `/login?next=` funcionar para páginas do portal que exigem login; verificar com teste BDD do cenário "Volta à página pedida"

## 3. Break-glass

- [x] 3.1 Adicionar comando `appaiforge hash-password` à CLI; verificar que o hash gerado é aceito por `verify_password` em teste unitário
- [x] 3.2 Implementar upsert/desativação do break-glass no startup a partir da ENV e recusa de editar/desativar/excluir o usuário `break_glass` no serviço de diretório (D7); verificar com testes unitários (ENV presente cria admin; ENV removida desativa e apaga sessões; operações de admin sobre ele são recusadas)
- [x] 3.3 Criar `/login/local`, sessão de 8 h, rate limit por (IP, e-mail), auditoria `breakglass_login`/`breakglass_login_failed` e banner de sessão de emergência no layout comum; verificar com testes de integração (bloqueio após 5 falhas, entradas de auditoria, expiração) e E2E no stack local (banner visível)

## 4. Login OIDC

- [x] 4.1 Implementar o cliente OIDC com discovery, reescrita para `oidc_internal_base_url` e validação de ID/access token via JWKS (D2, D11); verificar com testes unitários usando um IdP fake (JWKS e tokens assinados localmente): `iss`, `aud`, `nonce`, assinatura e expiração inválidos são recusados
- [x] 4.2 Implementar `GET /auth/login` e `GET /auth/callback` com cookie de tentativa cifrado, PKCE, mapeamento de papéis/grupos, upsert do usuário-sombra pelo `sub`, registro em `observed_idp_groups` e página "acesso não concedido" (D2, D4); verificar com testes de integração contra o IdP fake cobrindo os cenários de `oidc-authentication` (sucesso, `state` inválido, erro do IdP, sem papel, vários papéis, conflito de e-mail)
- [x] 4.3 Implementar a revalidação lazy com `SELECT … FOR UPDATE`, atualização de snapshot e encerramento em `invalid_grant`/tolerância esgotada (D5); verificar com testes de integração (papel trocado, grupo removido, usuário desativado, duas resoluções concorrentes gastando um único refresh)
- [x] 4.4 Implementar `GET /auth/logout` com `end_session_endpoint` e `id_token_hint`, e adaptar `/login` no modo oidc (botão SSO, redirecionamento automático com `next`); verificar com teste de integração da URL de logout e da página de login sem formulário

## 5. Administração no modo OIDC

- [x] 5.1 Tornar Admin › Usuários somente leitura no modo oidc (e-mail, tipo, último login) e recusar no serviço as operações de criar/alterar tipo/desativar/excluir nesse modo; verificar com testes BDD de `portal-identity` para os dois modos
- [x] 5.2 Remover a gestão de membros no modo oidc, adicionar sugestões de `observed_idp_groups` e o aviso para nome nunca visto ao criar grupo, e o aviso ao renomear; verificar com testes BDD (sugestão listada, aviso exibido, casamento exato sensível a maiúsculas no RBAC)

## 6. Edge e identidade das apps

- [x] 6.1 Criar `GET /internal/edge/auth/{slug}` (302 para `/login?next=`, 403, ou 200 + `X-AIDB-Identity`) e a emissão do JWT HS256 por sistema com `aud=aidb-app:{slug}` (D8, D9); verificar com testes de integração dos três desfechos e do conteúdo do JWT
- [x] 6.2 Adicionar o middleware forwardAuth antes do `stripPrefix` em `edge.publish_app_docker` e no `IngressRoute`/`Middleware` do `kubernetes_driver.publish` (e no `unpublish`), rodando `impact` antes de editar; verificar com os testes unitários dos dois drivers comparando o YAML/objetos gerados
- [x] 6.3 Reescrever `app_template/identity.py` (`current_identity(request)` + middleware 401, só stdlib) e atualizar `guidelines.py`, o placeholder do `afsupervisor` e a app do `harness/fake.py` para ler `X-AIDB-Identity`; verificar com testes unitários do template (assinatura, `aud` de outra app, expiração, ausência)
- [x] 6.4 Manter `/entry/{slug}` emitindo o `?t=` legado para apps antigas (D9) e registrar no código o motivo; verificar com teste de integração do redirecionamento
- [x] 6.5 Migrar os E2E que usam `/entry/{slug}` para abrir `/apps/{slug}` diretamente e adicionar E2E no stack local: link direto sem sessão volta à app após login, usuário sem acesso recebe 403, logout derruba a app aberta, header `X-AIDB-Identity` forjado pelo cliente não chega à app; verificar com `pytest portal/tests/e2e` contra `docker-compose.e2e.yml`

## 7. Keycloak e stack E2E OIDC

- [x] 7.1 Criar `deploy/keycloak/aidb-realm.json` (client `aidb-portal`, papéis, grupos, mapper de grupos sem caminho completo, access token de 5 min, usuários de teste) e verificar que o Keycloak importa o realm sem erros no log de start
- [x] 7.2 Criar `deploy/docker-compose.e2e-oidc.yml` (projeto `appaiforge-e2e-oidc`, Keycloak 8180 com `KC_HOSTNAME`/backchannel dinâmico, edge 8082, base própria, break-glass) e verificar `docker compose ... up -d --build` com portal sadio e discovery acessível pelo portal
- [x] 7.3 Criar `portal/tests/e2e_oidc/` (conftest próprio, aviso de não rodar junto do stack local) com os fluxos: login SSO por papel, usuário sem papel recusado, link de app sem sessão → Keycloak → volta à app, entrada direta logado, grupo cadastrado concede acesso e não cadastrado não, logout federado exige credenciais de novo, break-glass entra por `/login/local` e usuário comum é recusado lá; verificar com `pytest portal/tests/e2e_oidc` passando

## 8. Deploy e documentação

- [x] 8.1 Adicionar as variáveis de modo/OIDC/break-glass ao `deploy/docker-compose.yml` e ao chart Helm (`values.yaml`, `secret.yaml`, `deployment.yaml`) com default `local`; verificar com `helm template` renderizando as envs e o Secret
- [x] 8.2 Escrever o ADR `0027` (SSO OIDC, `Principal`, forwardAuth e JWT por app), marcar o 0006 como substituído e o 0014 como emendado, e atualizar o README com a configuração dos dois modos e do break-glass; verificar que os links do índice de ADRs resolvem
- [x] 8.3 Rodar a suíte completa (unit, BDD, integração, E2E local e E2E OIDC) e `detect_changes` do GitNexus antes do commit; verificar todos verdes e risco reportado

## Workflow follow-up

- Arquivar a change após revisão e com os dois stacks E2E verdes.
- Change futura: remover o handoff legado `?t=` quando não houver apps antigas.
- Change futura: isolar o cookie do portal das apps (subdomínio ou remoção no edge).
