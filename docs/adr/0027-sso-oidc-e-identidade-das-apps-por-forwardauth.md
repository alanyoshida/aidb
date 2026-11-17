# 0027 — SSO por OIDC opcional; acesso às apps verificado no edge e identidade por app em JWT

* Status: aceito
* Data: 2026-11-16
* Decidida em: change `add-oidc-sso`
* Substitui: [ADR 0006](0006-identidade-injetada-por-token-hmac.md) (handoff `?t=` mantido só como
  compatibilidade para apps antigas)
* Emenda: [ADR 0014](0014-rbac-com-tipos-globais-de-usuario.md) (autenticação deixa de ser só local;
  no modo OIDC tipo global e grupos vêm do IdP)

## Contexto

Em ambiente corporativo, usuários, grupos e papéis vivem num diretório (LDAP) federado por um IdP
(Keycloak) e são concedidos por um processo externo de aprovação — não pelo admin do portal. O
portal só sabia autenticar por e-mail e senha. Além disso, o acesso às apps tinha duas falhas: o link
direto `/apps/{slug}` sem sessão não voltava à app depois do login, e a app guardava sessão própria
após o handoff `?t=`, então logout ou perda de acesso no portal não a alcançavam.

## Decisão

1. **Modo de autenticação por configuração** (`APPAIFORGE_AUTH_MODE` = `local` | `oidc`), gravado na
   base no primeiro boot; um modo divergente depois impede o boot. Trocar o modo de uma instalação
   não é suportado.
2. **Modo OIDC**: authorization code com PKCE contra o IdP; o tipo global vem do maior papel do token
   (`admin` > `editor` > `app_user`, sem papel = login recusado) e os grupos do claim de grupos,
   casados pelo nome exato com grupos cadastrados pelo admin no portal (o vínculo grupo→sistema
   continua no portal). Usuário local vira sombra identificada pelo `sub`. A sessão é revalidada
   com refresh token a no máximo cada 5 min (revogação no IdP vale nesse prazo); logout é federado.
3. **Admin break-glass** definido só por ENV, disponível nos dois modos por `/login/local`, sempre
   `admin`, sessão de 8 h, rate limit, auditoria e aviso visual; não é gerenciável pela UI.
4. **Um `Principal` por requisição** (quem é o usuário, tipo e grupos), independente do modo, usado
   pelo RBAC, pelas páginas e pelo edge.
5. **Acesso às apps verificado pelo edge**: `forwardAuth` do Traefik (compose e IngressRoute) chama
   o portal antes de cada requisição a `/apps/{slug}`. Sem sessão → login com retorno à app; sem
   acesso → 403; com acesso → o portal devolve `X-AIDB-Identity`, que o Traefik injeta na app.
6. **Identidade por app**: `X-AIDB-Identity` é um JWT HS256 assinado com o segredo do sistema
   (`APP_IDENTITY_SECRET`), audiência `aidb-app:{slug}`, validade curta, com `sub`, e-mail, tipo e
   grupos. A app valida a cada requisição e não mantém sessão própria. O token do IdP nunca chega
   à app.

## Alternativas consideradas

- **Repassar o access token do IdP à app** — descartado: a app roda código gerado pelo agente; um
  token reaproveitável contra o portal e outras apps é exatamente o que o confinamento evita.
- **JWT RS256 com JWKS do portal** — descartado por ora: exige distribuir chave pública e não
  acrescenta isolamento entre apps; segredo por sistema + `aud` já impedem uso cruzado.
- **Verificação na própria app (middleware gerado)** — descartado: segurança dependeria de código
  gerado pelo agente; o edge é o ponto de controle.
- **Cookie por app emitido no `/entry`** — descartado: logout não propaga e o link direto continua
  quebrado.
- **Grupos via Admin API do Keycloak** — descartado: acopla o portal a um IdP específico; o admin
  cadastra o nome e o portal sugere nomes já vistos em tokens.
- **Vincular contas locais ao IdP pelo e-mail** — descartado: troca de modo não é suportada.

## Consequências

- O portal fora do ar derruba o acesso a todas as apps (fail-closed, desejado para autorização), e
  cada requisição de app custa uma consulta ao portal.
- Revogação no IdP leva até 5 min; logout e desvínculo no portal valem na requisição seguinte.
- O handoff `?t=` continua emitido por `/entry/{slug}` só para apps geradas antes desta decisão;
  remover quando não houver mais apps antigas.
- O cookie de sessão do portal ainda chega ao servidor das apps (mesma origem); isolá-lo (subdomínio
  ou remoção no edge) fica para decisão futura.
