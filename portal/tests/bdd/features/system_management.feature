Feature: Gestão de sistemas
  Como editor
  Quero cadastrar sistemas com slug único e provedor de LLM
  Para organizar as apps geradas por banco de dados
  # Fonte: specs/system-management/spec.md

  Scenario: Slug duplicado é rejeitado
    Given um editor autenticado com o sistema "erp" criado
    When ele cria um sistema com nome "Outro" e slug "erp"
    Then a criação é recusada por slug já existente

  Scenario: Cadastro sem escolha de provedor usa GLM
    Given um editor autenticado sem sistema criado
    When ele cria um sistema com nome "CRM" e slug "crm" sem informar provedor
    Then o sistema usa o provedor "glm" com o modelo padrão

  Scenario: Dono altera provedor do sistema
    Given um editor autenticado com o sistema "erp" criado
    When ele altera o provedor do sistema para "anthropic"
    Then o sistema passa a usar o provedor "anthropic"
