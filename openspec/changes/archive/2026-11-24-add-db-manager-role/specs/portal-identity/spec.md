# Spec Delta

## ADDED Requirements

### Requirement: Capacidade de DB Manager acumulável ao tipo
O portal SHALL suportar a capacidade de DB Manager como atributo do usuário independente do tipo global, de modo que um usuário de qualquer tipo possa tê-la sem perder as capacidades do seu tipo. Quem tem a capacidade SHALL poder gerir o catálogo de conexões de banco e as autorizações por sistema. O tipo `admin` SHALL ter essas mesmas permissões sem precisar da capacidade.

#### Scenario: Editor que também é DB Manager
- **WHEN** um usuário do tipo `editor` com a capacidade de DB Manager usa o portal
- **THEN** ele cria e gerencia sistemas como editor e também gere o catálogo de conexões

#### Scenario: DB Manager que não é editor
- **WHEN** um usuário do tipo `app_user` com a capacidade de DB Manager usa o portal
- **THEN** ele gere o catálogo de conexões e as autorizações, e continua sem poder criar sistemas nem acessar o chat de geração

#### Scenario: Admin gere o catálogo sem a capacidade
- **WHEN** um usuário do tipo `admin` sem a capacidade de DB Manager abre o catálogo de conexões
- **THEN** o portal permite todas as ações do catálogo

#### Scenario: Usuário sem a capacidade
- **WHEN** um `editor` ou `app_user` sem a capacidade de DB Manager tenta abrir o catálogo de conexões
- **THEN** o portal recusa com mensagem de permissão insuficiente, e o catálogo não aparece no seu menu

### Requirement: Concessão de DB Manager pelo admin no modo local
No modo `local`, o portal SHALL permitir que administradores concedam e retirem a capacidade de DB Manager de um usuário, ao criá-lo ou depois. No modo `oidc`, o portal SHALL NOT oferecer essa ação — a capacidade vem do IdP conforme a capability `oidc-authentication` — e SHALL apenas exibi-la na lista de usuários.

#### Scenario: Admin concede a capacidade
- **WHEN** no modo `local` um admin marca um usuário `editor` como DB Manager
- **THEN** o usuário passa a gerir o catálogo de conexões, mantendo o tipo `editor`

#### Scenario: Admin retira a capacidade
- **WHEN** no modo `local` um admin retira a capacidade de DB Manager de um usuário
- **THEN** o usuário deixa de acessar o catálogo, e as conexões e autorizações que ele criou permanecem

#### Scenario: Não-admin não concede
- **WHEN** um DB Manager que não é admin tenta conceder a capacidade a outro usuário
- **THEN** o portal recusa a operação

#### Scenario: Somente leitura no modo OIDC
- **WHEN** no modo `oidc` um admin abre a administração de usuários
- **THEN** vê quais usuários são DB Managers, sem ação para conceder ou retirar a capacidade
