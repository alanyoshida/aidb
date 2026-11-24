# Spec Delta

## ADDED Requirements

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
