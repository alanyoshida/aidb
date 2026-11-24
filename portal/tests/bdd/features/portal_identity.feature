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

  # --- Capacidade de DB Manager (change add-db-manager-role) ---

  Scenario: Editor que também é DB Manager
    Given um usuário do tipo "editor" que é DB Manager
    When ele cria um sistema com nome "Loja" e slug "loja"
    Then o sistema é criado no estado "provisioning" com ele como dono
    And ele pode gerir o catálogo de conexões

  Scenario: DB Manager que não é editor
    Given um usuário do tipo "app_user" que é DB Manager
    When ele cria um sistema com nome "Meu" e slug "meu"
    Then a criação é recusada por permissão insuficiente
    And ele pode gerir o catálogo de conexões
    And ele não pode usar o chat de geração

  Scenario: Admin gere o catálogo sem a capacidade
    Given um usuário do tipo "admin" autenticado
    Then ele pode gerir o catálogo de conexões

  Scenario: Usuário sem a capacidade
    Given um usuário do tipo "editor" autenticado
    Then ele não pode gerir o catálogo de conexões

  Scenario: Admin concede a capacidade
    Given um admin no modo local e um usuário "dba@t.local" do tipo "editor"
    When o admin marca "dba@t.local" como DB Manager
    Then "dba@t.local" pode gerir o catálogo e continua do tipo "editor"

  Scenario: Admin retira a capacidade
    Given um admin no modo local e um usuário "dba@t.local" do tipo "editor"
    When o admin marca "dba@t.local" como DB Manager
    And o admin retira de "dba@t.local" a capacidade de DB Manager
    Then "dba@t.local" não pode gerir o catálogo

  Scenario: Não-admin não concede
    Given um admin no modo local e um usuário "dba@t.local" do tipo "editor"
    When o admin marca "dba@t.local" como DB Manager
    Then "dba@t.local" não consegue conceder a capacidade a outro usuário

  Scenario: Somente leitura no modo OIDC
    Given o portal no modo "oidc" com um admin break-glass
    And um usuário que entrou pelo IdP com o papel de DB Manager
    Then a lista de usuários mostra que ele é DB Manager
    And o admin não consegue conceder nem retirar a capacidade
