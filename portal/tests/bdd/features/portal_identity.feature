Feature: Autenticação local no portal
  Como usuário do portal
  Quero autenticar-me com e-mail e senha
  Para acessar apenas o que me é permitido
  # Fonte: specs/portal-identity/spec.md

  Scenario: Login com credenciais válidas
    Given um usuário ativo registrado com e-mail e senha
    When ele autentica com e-mail "editor@test.local" e senha "senha-ok"
    Then uma sessão é iniciada com sucesso

  Scenario: Login com credenciais inválidas
    Given um usuário ativo registrado com e-mail e senha
    When ele autentica com e-mail "editor@test.local" e senha "senha-errada"
    Then o login é rejeitado sem revelar qual campo falhou

  Scenario: Logout
    Given um usuário ativo registrado com e-mail e senha
    When ele autentica com e-mail "editor@test.local" e senha "senha-ok"
    When ele encerra a sessão
    Then requisições posteriores com aquela sessão são recusadas

  # --- Tipos globais de usuário ---

  Scenario: Editor cria sistema
    Given um usuário do tipo "editor" autenticado
    When ele cria um sistema com nome "ERP" e slug "erp"
    Then o sistema é criado no estado "provisioning" com ele como dono

  Scenario: app_user não cria sistema
    Given um usuário do tipo "app_user" autenticado
    When ele cria um sistema com nome "Meu" e slug "meu"
    Then a criação é recusada por permissão insuficiente

  Scenario: Admin tem acesso total
    Given um usuário do tipo "admin" autenticado
    When ele cria um sistema com nome "Auditoria" e slug "auditoria"
    Then o sistema é criado no estado "provisioning" com ele como dono

  # --- Visibilidade de sistemas ---

  Scenario: Membro de grupo acessa sistema vinculado
    Given um sistema "erp" de um editor
    And um "app_user" membro do grupo "clientes" vinculado ao sistema "erp"
    Then o "app_user" enxerga o sistema "erp"
    And um "app_user" sem vínculo não enxerga o sistema "erp"
