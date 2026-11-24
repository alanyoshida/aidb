# oidc-authentication Specification

## Purpose

Define o login SSO do portal por OpenID Connect contra um IdP externo, quando o modo de autenticação é `oidc`: redirecionamento e retorno, mapeamento de papel e grupos a partir do token, usuário-sombra, revogação pelo IdP e logout federado.

## Requirements

### Requirement: Login por authorization code com o IdP
No modo `oidc`, o portal SHALL autenticar usuários redirecionando-os ao IdP configurado pelo fluxo authorization code com PKCE, e SHALL aceitar o retorno somente se o `state` corresponder à tentativa iniciada naquele navegador e o ID token for válido (assinatura do IdP, emissor e audiência configurados, `nonce` da tentativa, dentro da validade).

#### Scenario: Login SSO bem-sucedido
- **WHEN** um usuário não autenticado inicia o login e se autentica no IdP com um papel reconhecido
- **THEN** o IdP o devolve ao portal, que inicia sua sessão e o leva à área autenticada

#### Scenario: Retorno com state inválido
- **WHEN** o portal recebe um retorno do IdP cujo `state` não corresponde a nenhuma tentativa iniciada naquele navegador
- **THEN** o portal recusa o login sem criar sessão

#### Scenario: Token com nonce ou emissor divergente
- **WHEN** o ID token recebido tem `nonce`, emissor ou audiência diferentes dos esperados, ou assinatura inválida
- **THEN** o portal recusa o login sem criar sessão

#### Scenario: Erro devolvido pelo IdP
- **WHEN** o IdP devolve o usuário com erro (por exemplo, login cancelado)
- **THEN** o portal exibe mensagem genérica de falha de login, sem criar sessão

### Requirement: Papel global vindo do token
No modo `oidc`, o portal SHALL derivar o tipo global do usuário dos papéis presentes no token: `admin`, `editor` e `app_user` mapeiam para os tipos de mesmo nome; com mais de um papel reconhecido, prevalece o de maior capacidade (`admin` > `editor` > `app_user`); sem nenhum papel reconhecido, o login SHALL ser recusado.

#### Scenario: Papel único
- **WHEN** um usuário entra com o papel `editor` no token
- **THEN** sua sessão no portal tem o tipo `editor`

#### Scenario: Vários papéis
- **WHEN** um usuário entra com os papéis `app_user` e `admin` no token
- **THEN** sua sessão no portal tem o tipo `admin`

#### Scenario: Sem papel reconhecido
- **WHEN** um usuário se autentica no IdP sem nenhum dos papéis `admin`, `editor` ou `app_user`
- **THEN** o portal recusa o login com mensagem de acesso não concedido e não cria sessão

### Requirement: Usuário-sombra provisionado no login
No modo `oidc`, o portal SHALL manter um registro local para cada usuário que entra pelo IdP, identificado pelo identificador de sujeito (`sub`) do IdP, criado no primeiro login e com e-mail e tipo atualizados a cada login, de modo que posse de sistemas, histórico e auditoria continuem atribuíveis ao usuário.

#### Scenario: Primeiro login cria o usuário
- **WHEN** um usuário entra pelo IdP pela primeira vez
- **THEN** o portal cria seu registro local com o `sub`, o e-mail e o tipo derivados do token

#### Scenario: Login seguinte atualiza o usuário
- **WHEN** um usuário já conhecido entra com e-mail ou papel diferentes no IdP
- **THEN** o registro local é o mesmo (pelo `sub`) e passa a refletir o novo e-mail e o novo tipo

### Requirement: Grupos vindos do token
No modo `oidc`, o portal SHALL considerar como grupos do usuário os nomes presentes no claim de grupos do token que casem exatamente (sensível a maiúsculas) com o nome de um grupo cadastrado no portal; nomes sem grupo cadastrado SHALL ser ignorados para fins de acesso.

#### Scenario: Grupo cadastrado concede acesso
- **WHEN** o token de um usuário traz o grupo `financeiro` e existe um grupo `financeiro` cadastrado no portal vinculado ao sistema X
- **THEN** o usuário pode acessar o sistema X

#### Scenario: Grupo não cadastrado é ignorado
- **WHEN** o token de um usuário traz o grupo `ti-infra` e não há grupo com esse nome no portal
- **THEN** esse grupo não concede acesso a nenhum sistema

#### Scenario: Diferença de maiúsculas não casa
- **WHEN** o token traz `Financeiro` e o grupo cadastrado é `financeiro`
- **THEN** o grupo não é considerado do usuário

### Requirement: Sessão sujeita ao IdP
No modo `oidc`, o portal SHALL revalidar periodicamente a sessão do usuário junto ao IdP, atualizando tipo e grupos a cada revalidação, e SHALL encerrar a sessão do portal quando o IdP recusar a revalidação (usuário desativado, sessão no IdP encerrada ou expirada). O intervalo entre revalidações SHALL ser de no máximo 5 minutos.

#### Scenario: Papel removido no IdP
- **WHEN** o papel `editor` de um usuário logado é removido no IdP e ele recebe `app_user`
- **THEN** em até 5 minutos o portal passa a tratá-lo como `app_user`

#### Scenario: Grupo removido no IdP
- **WHEN** um usuário logado perde no IdP o grupo que lhe dava acesso ao sistema X
- **THEN** em até 5 minutos o acesso ao sistema X e à sua app passa a ser recusado

#### Scenario: Usuário desativado no IdP
- **WHEN** um usuário logado é desativado no IdP
- **THEN** em até 5 minutos sua sessão no portal é encerrada e as próximas requisições exigem novo login

### Requirement: Logout federado
No modo `oidc`, o logout no portal SHALL encerrar a sessão do portal e redirecionar o usuário ao IdP para encerrar também a sessão SSO, voltando em seguida ao portal.

#### Scenario: Logout encerra o SSO
- **WHEN** um usuário logado por OIDC faz logout e depois tenta entrar de novo
- **THEN** o IdP pede credenciais novamente em vez de reaproveitar a sessão SSO anterior

### Requirement: Sem credenciais locais no modo OIDC
No modo `oidc`, o portal SHALL NOT aceitar login por e-mail e senha de usuários comuns; apenas o admin break-glass entra com credencial local.

#### Scenario: Usuário comum tenta login local
- **WHEN** no modo `oidc` alguém tenta entrar pela rota de login local com e-mail e senha de um usuário que não é o break-glass
- **THEN** o portal recusa com mensagem genérica

### Requirement: Capacidade de DB Manager vinda do token
No modo `oidc`, o portal SHALL conceder a capacidade de DB Manager ao usuário cujo token traz o papel `db_manager` no mesmo claim de papéis usado para o tipo global. O papel `db_manager` SHALL NOT definir o tipo global nem bastar, sozinho, para o login. A capacidade SHALL ser atualizada a cada login e a cada revalidação da sessão.

#### Scenario: Editor e DB Manager no token
- **WHEN** um usuário entra com os papéis `editor` e `db_manager` no token
- **THEN** sua sessão tem o tipo `editor` e a capacidade de DB Manager

#### Scenario: Token sem o papel
- **WHEN** um usuário entra com o papel `editor` e sem `db_manager`
- **THEN** sua sessão tem o tipo `editor` e não tem a capacidade de DB Manager

#### Scenario: Somente db_manager não entra
- **WHEN** um usuário se autentica no IdP com o papel `db_manager` e sem nenhum dos papéis `admin`, `editor` ou `app_user`
- **THEN** o portal recusa o login com mensagem de acesso não concedido e não cria sessão

#### Scenario: Papel removido no IdP
- **WHEN** o papel `db_manager` de um usuário logado é removido no IdP
- **THEN** em até 5 minutos o portal deixa de permitir que ele gira o catálogo de conexões
