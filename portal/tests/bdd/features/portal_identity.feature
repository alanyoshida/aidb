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

  # --- Retorno ao destino após o login (change add-oidc-sso) ---

  Scenario: Volta à página pedida
    Given um usuário ativo registrado com e-mail e senha
    When ele abre "/systems/abc" sem sessão e é levado ao login
    And ele entra pelo formulário de login
    Then ele chega a "/systems/abc"

  Scenario: Destino externo é ignorado
    Given um usuário ativo registrado com e-mail e senha
    When o login é iniciado com destino "https://outro.example/roubo"
    And ele entra pelo formulário de login
    Then ele chega a "/"

  # --- Administração no modo OIDC (change add-oidc-sso) ---

  Scenario: Gestão de usuários indisponível no modo OIDC
    Given o portal no modo "oidc" com um admin break-glass
    And um usuário que já entrou pelo IdP
    Then o admin não consegue criar, alterar tipo, desativar nem excluir usuários
    And o admin não consegue adicionar nem remover membros de grupos

  Scenario: Admin cadastra grupo com nome do IdP
    Given o portal no modo "oidc" com um admin break-glass
    And um sistema "vendas" de um editor
    When o admin cadastra o grupo "financeiro" e o vincula ao sistema "vendas"
    Then um usuário cujo token traz o grupo "financeiro" acessa o sistema "vendas"
    And um usuário cujo token traz o grupo "Financeiro" não acessa o sistema "vendas"

  Scenario: Sugestão de nomes vistos
    Given o portal no modo "oidc" com um admin break-glass
    And o grupo "marketing" foi visto em um token
    Then o portal sugere "marketing" ao cadastrar grupo
    And cadastrar "nunca-visto" mostra o aviso de grupo sem usuários
    And cadastrar "marketing" não mostra aviso

  Scenario: Aviso ao renomear no modo OIDC
    Given o portal no modo "oidc" com um admin break-glass
    Then renomear grupo mostra o aviso de nome idêntico ao do IdP

  Scenario: Sem aviso ao renomear no modo local
    Given um usuário do tipo "admin" autenticado
    Then renomear grupo não mostra aviso
