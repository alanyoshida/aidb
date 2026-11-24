# Autenticação: modo local, SSO por OIDC e break-glass

← [README](../README.md) · decisão: [ADR 0027](adr/0027-sso-oidc-e-identidade-das-apps-por-forwardauth.md)

O portal autentica em **um** de dois modos, escolhido por `APPAIFORGE_AUTH_MODE`:

| Modo | Quem entra | Tipo global e grupos | Gestão de usuários no portal |
|---|---|---|---|
| `local` (padrão) | e-mail e senha cadastrados pelo admin | definidos pelo admin no portal | criar, trocar tipo, desativar, excluir, membros de grupo |
| `oidc` | conta do IdP (Keycloak etc.), pelo fluxo authorization code + PKCE | vêm do token, a cada login e a cada revalidação (≤ 5 min) | só leitura (quem já entrou, tipo, último login) |

O modo é **gravado na base no primeiro boot**. Subir depois com outro modo faz o portal recusar o
boot com uma mensagem explicando a divergência — trocar o modo de uma instalação não é suportado.

## Modo OIDC

Variáveis (todas com prefixo `APPAIFORGE_`):

| Variável | Exemplo | O quê |
|---|---|---|
| `AUTH_MODE` | `oidc` | liga o SSO |
| `PUBLIC_BASE_URL` | `https://aidb.empresa.com` | URL do portal como o navegador vê (base do `redirect_uri`) |
| `OIDC_ISSUER` | `https://sso.empresa.com/realms/aidb` | emissor público; o `iss` dos tokens é validado contra ele |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | `aidb-portal` / … | client confidencial no IdP |
| `OIDC_INTERNAL_BASE_URL` | `http://keycloak:8080` | opcional: base interna do IdP para discovery/token/JWKS quando o portal não alcança o endereço público |
| `OIDC_ROLES_CLAIM` | `realm_access.roles` | caminho do claim de papéis no access token |
| `OIDC_GROUPS_CLAIM` | `groups` | claim com os nomes dos grupos |
| `OIDC_REVALIDATE_SECONDS` | `300` | intervalo máximo entre revalidações (refresh token) |

Sem emissor, client ou URL pública, o portal não sobe e diz qual variável falta.

**No IdP** (Keycloak, por exemplo):

- client confidencial com *standard flow*, PKCE `S256`, redirect `<PUBLIC_BASE_URL>/auth/callback`
  e post-logout redirect `<PUBLIC_BASE_URL>/login`;
- realm roles `admin`, `editor`, `app_user` atribuídas pelo processo de aprovação de acesso, e
  `db_manager` para quem gere o catálogo de bancos de dados;
- mapper *Group Membership* com **Full group path desligado**, no ID token e no access token.

**Papel**: vale o maior entre `admin` > `editor` > `app_user`. Sem nenhum deles o login é recusado
("acesso não concedido").

**DB Manager**: o papel `db_manager`, no mesmo claim de papéis, concede a capacidade de gerir o
catálogo de conexões de banco e as autorizações por sistema. Ele se soma ao tipo e não o define: o
usuário precisa também de `admin`, `editor` ou `app_user`, e só `db_manager` não entra. Para criar
o papel no Keycloak: *Realm roles* → *Create role* `db_manager`; para conceder: *Users* → usuário →
*Role mapping* → *Assign role*. Retirar o papel vale na próxima revalidação, como os demais.
No modo `local`, o admin concede a capacidade em *Administração* → *Usuários*.

**Grupos**: o admin cadastra no portal um grupo com **exatamente** o nome que vem no token
(maiúsculas contam) e o vincula a sistemas. Nomes do token sem grupo cadastrado não dão acesso. Ao
cadastrar, o portal sugere nomes já vistos em logins e avisa quando o nome nunca apareceu; renomear
um grupo corta o acesso se o nome deixar de bater com o do IdP.

**Revogação**: perder o papel/grupo ou ser desativado no IdP vale em até 5 minutos (próxima
revalidação). Se o IdP ficar fora do ar, a sessão é mantida por até 60 s além do prazo e depois
encerrada. Logout no portal também encerra a sessão SSO no IdP.

## Admin break-glass

Um administrador de emergência, definido **só por ENV**, que funciona nos dois modos:

```bash
cd portal && uv run appaiforge hash-password      # pede a senha e imprime o hash
```

```bash
APPAIFORGE_BREAKGLASS_EMAIL=emergencia@empresa.com
APPAIFORGE_BREAKGLASS_PASSWORD_HASH='scrypt$16384$8$1$...'   # num .env do compose, escreva cada $ como $$
```

Entra por `/login/local` (sem link nas páginas no modo OIDC). É sempre `admin`, sem grupos, com
sessão de até 8 h; cada tentativa (certa ou errada) vai para a auditoria de gestão, a interface mostra
uma faixa de "sessão de emergência", e 5 falhas por IP+e-mail em 15 min bloqueiam novas tentativas.
Não pode ser editado, desativado nem excluído pela interface. Remover as variáveis e reiniciar
desativa o usuário e derruba as sessões dele.

## Acesso às apps

Toda requisição a `/apps/<slug>` passa antes pelo portal (`forwardAuth` do Traefik, nos dois
drivers):

- sem sessão → login e, depois, de volta ao mesmo endereço da app;
- logado sem acesso ao sistema → 403;
- com acesso → a app recebe o header `X-AIDB-Identity`, um JWT HS256 assinado com o segredo do
  sistema (`APP_IDENTITY_SECRET`), audiência `aidb-app:<slug>`, com `sub`, `email`, `user_type` e
  `groups`. Um header enviado pelo cliente é sempre sobrescrito.

A app valida o header em toda requisição (helper `appaiforge/app_template/identity.py`, copiado pelas
guidelines) e não guarda sessão própria — logout ou perda de acesso no portal valem na requisição
seguinte. O token do IdP nunca chega à app.

Apps geradas antes desta mudança só conhecem o handoff antigo `?t=`: continuam funcionando pelo botão
**Abrir app** (`/entry/<slug>`), mas o link direto só funciona depois de regenerá-las.

## E2E com Keycloak local

```bash
docker compose -f deploy/docker-compose.e2e-oidc.yml up -d --build   # portal :8082, Keycloak :8180
cd portal && uv run pytest tests/e2e_oidc
```

Realm importado de [`deploy/keycloak/aidb-realm.json`](../deploy/keycloak/aidb-realm.json) (usuários
`e2e-admin`, `e2e-editor`, `e2e-dba` (editor e DB Manager), `e2e-financeiro`, `e2e-vendas`,
`e2e-semrole`, senha `e2e-senha`; console
admin `admin`/`admin`). Não rode junto com a suíte `tests/e2e` (stack 8081).
