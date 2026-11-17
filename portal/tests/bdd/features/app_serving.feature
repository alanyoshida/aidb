Feature: Serviço da app gerada
  Como usuário do portal
  Quero acessar a app do sistema com minha identidade já autenticada
  Para usar os dados sem logar de novo
  # Fonte: specs/app-serving/spec.md (change add-oidc-sso)

  Scenario: App identifica o usuário
    Given um sistema "erp" ativo com um membro de grupo vinculado
    When o membro abre "/apps/erp/" logado no portal
    Then a app reconhece o membro pelo identificador, tipo e grupos

  Scenario: Identidade de outra app
    Given um sistema "erp" ativo com um membro de grupo vinculado
    When chega à app "erp" uma identidade emitida para a app "rh"
    Then a app recusa a identidade

  Scenario: Token de identidade inválido
    Given um sistema "erp" ativo com um membro de grupo vinculado
    When chega à app uma identidade expirada
    Then a app recusa a identidade

  Scenario: Usuário não logado abre o link da app
    Given um sistema "erp" ativo com um membro de grupo vinculado
    When alguém sem sessão abre "/apps/erp/relatorios"
    Then é levado ao login com retorno a "/apps/erp/relatorios"

  Scenario: Usuário sem acesso é recusado
    Given um sistema "erp" ativo com um membro de grupo vinculado
    When um usuário sem vínculo abre "/apps/erp/"
    Then o portal recusa com permissão insuficiente
