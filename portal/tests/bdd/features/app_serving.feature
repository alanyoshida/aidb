Feature: Serviço da app gerada
  Como usuário do portal
  Quero acessar a app do sistema com minha identidade já autenticada
  Para usar os dados sem logar de novo
  # Fonte: specs/app-serving/spec.md

  Scenario: App identifica o usuário
    Given um sistema com segredo de identidade
    When o portal assina um token para o usuário "u1" do tipo "app_user"
    Then a app reconhece "u1" como "app_user" pelo token

  Scenario: Token de identidade inválido
    Given um sistema com segredo de identidade
    When a app recebe um token assinado com segredo errado
    Then a app recusa a sessão

  Scenario: Token de identidade expirado
    Given um sistema com segredo de identidade
    When a app recebe um token válido emitido há mais de uma hora
    Then a app recusa a sessão
