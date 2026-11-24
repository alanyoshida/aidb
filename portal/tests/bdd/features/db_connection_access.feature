Feature: Acesso de sistemas às conexões do catálogo
  Como DB Manager
  Quero autorizar conexões do catálogo para sistemas, com teto de modo de acesso
  Para que cada sistema use só o banco que o dono ativou, no modo permitido
  # Fonte: specs/db-connection-access/spec.md (change add-db-manager-role)

  Scenario: DB Manager autoriza conexão para um sistema
    Given um DB Manager, o sistema "x" de um editor e a conexão "Vendas prod" no catálogo
    When o DB Manager autoriza "Vendas prod" para o sistema "x"
    Then a conexão "Vendas prod" aparece disponível e inativa no sistema "x"
    And o agente do sistema "x" não recebe nenhuma conexão

  Scenario: Dono ativa a conexão
    Given um DB Manager, o sistema "x" de um editor e a conexão "Vendas prod" no catálogo
    When o DB Manager autoriza "Vendas prod" para o sistema "x"
    And o dono ativa "Vendas prod" no sistema "x" com alias "vendas" e modo "read_only"
    Then o sistema "x" recebe a conexão com alias "vendas" no modo "read_only"

  Scenario: Modo acima do teto é recusado
    Given um DB Manager, o sistema "x" de um editor e a conexão "Vendas prod" no catálogo
    When o DB Manager autoriza "Vendas prod" para o sistema "x"
    Then ativar "Vendas prod" no sistema "x" em "schema_admin" é recusado por estar acima do teto

  Scenario: Revogação de conexão ativa
    Given um DB Manager, o sistema "x" de um editor e a conexão "Vendas prod" no catálogo
    When o DB Manager autoriza "Vendas prod" para o sistema "x"
    And o dono ativa "Vendas prod" no sistema "x" com alias "vendas" e modo "read_write"
    And o DB Manager revoga "Vendas prod" do sistema "x"
    Then o agente do sistema "x" não recebe nenhuma conexão
    And a aba de conexões do sistema "x" mostra que "vendas" foi revogada
