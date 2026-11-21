Feature: Sistema só implantação
  Como responsável por um portal de produção
  Quero implantar só versões aprovadas de um repositório GitLab, sem agente
  Para que produção rode exatamente o que passou pela branch de destino
  # Fonte: specs/deploy-only-system/spec.md (cenários de interface estão em tests/e2e_gitlab)

  Scenario: Tipo padrão
    Given um portal de desenvolvimento
    When um editor cria um sistema sem escolher o tipo
    Then o sistema é criado como "com agente"

  Scenario: Criação recusada em produção
    Given um portal de produção
    When um editor tenta criar um sistema com agente
    Then a criação é recusada explicando que este portal só aceita sistemas só implantação

  Scenario: Nenhum agente nem credencial de LLM
    Given um sistema só implantação ativo ligado ao repositório
    Then nenhum processo de agente roda no container e nenhuma variável de LLM existe nele

  Scenario: Padrões ao configurar
    Given um sistema só implantação ativo ligado ao repositório
    Then a branch de destino é "main" e o padrão de tags é "v*"

  Scenario: Tags listadas em ordem de versão
    Given um sistema só implantação ativo ligado ao repositório
    And o repositório tem as tags "v1.0.1", "v1.0.10", "v1.0.2" e "rascunho"
    Then a lista de versões é "v1.0.10", "v1.0.2", "v1.0.1"

  Scenario: Tag aprovada implantada sem escrever no repositório
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    When o editor implanta "v1.0.0"
    Then a app responde "VERSAO-1"
    And o histórico mostra "v1.0.0" com origem "manual" e resultado "succeeded"
    And nenhuma ref do repositório remoto mudou

  Scenario: Tag fora da branch de destino recusada
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    And o editor implantou "v1.0.0"
    And a versão "v9.0.0" fora da branch de destino
    When o editor implanta "v9.0.0"
    Then a implantação é recusada explicando que a versão não passou pela branch de destino
    And a app responde "VERSAO-1"

  Scenario: Versão com falha volta para a anterior
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    And o editor implantou "v1.0.0"
    And a versão "v2.0.0" na branch de destino com uma app que não sobe
    When o editor implanta "v2.0.0"
    Then a app responde "VERSAO-1"
    And o histórico mostra "v2.0.0" com origem "manual" e resultado "rolled_back"

  Scenario: Rollback para uma tag anterior
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    And o editor implantou "v1.0.0"
    And a versão "v1.1.0" na branch de destino com a app "VERSAO-1-1"
    And o editor implantou "v1.1.0"
    When o editor implanta "v1.0.0"
    Then a app responde "VERSAO-1"
    And a versão atual é "v1.0.0"

  Scenario: Rollback permanece no modo automático
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    And o editor implantou "v1.0.0"
    And a versão "v1.1.0" na branch de destino com a app "VERSAO-1-1"
    And o editor implantou "v1.1.0"
    And o editor implantou "v1.0.0"
    And o modo automático está ligado
    When a verificação automática roda
    Then a versão atual é "v1.0.0"

  Scenario: Tag nova implantada sozinha
    Given um sistema só implantação ativo ligado ao repositório
    And o modo automático está ligado
    And a versão "v1.0.0" na branch de destino com a app "AUTOMATICA"
    When a verificação automática roda
    Then a versão atual é "v1.0.0"
    And o histórico mostra "v1.0.0" com origem "polling" e resultado "succeeded"

  Scenario: Modo manual
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    When a verificação automática roda
    Then nenhuma implantação foi feita

  Scenario: Webhook com segredo errado
    Given um sistema só implantação ativo ligado ao repositório
    When o webhook é chamado com o segredo "errado"
    Then a chamada é recusada com 401

  Scenario: Conexão faltando
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino exigindo a conexão "vendas"
    When o editor implanta "v1.0.0"
    Then a implantação é recusada listando "vendas" como faltante

  Scenario: Versão sem manifesto
    Given um sistema só implantação ativo ligado ao repositório
    And a versão "v1.0.0" na branch de destino com a app "VERSAO-1"
    When o editor implanta "v1.0.0"
    Then a implantação avisa que não pôde conferir as conexões
