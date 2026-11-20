Feature: Repositório do sistema fora do alcance do agente
  Como plataforma multi-tenant
  Quero que o histórico git de cada sistema fique fora do workspace
  Para que nada escrito pelo agente seja executado pelo portal
  # Fonte: specs/workspace-repository/spec.md (driver Docker; a paridade com o driver
  # Kubernetes é coberta em tests/integration/test_driver_parity.py)

  Scenario: Agente não alcança o histórico
    Given um sistema com um checkpoint
    Then o repositório de checkpoints não está em nenhum caminho do workspace

  Scenario: Diretório .git no workspace não é o repositório
    Given um sistema com um checkpoint
    And o agente cria um diretório ".git" no workspace com conteúdo próprio
    When um novo checkpoint é criado
    Then o conteúdo do ".git" do workspace não entra no checkpoint

  Scenario: Hook plantado no workspace não executa
    Given um sistema com um checkpoint
    And o agente planta "um hook pre-commit" no workspace
    When um novo checkpoint é criado
    Then o checkpoint existe e nada plantado executou

  Scenario: Filtro declarado em atributos não executa
    Given um sistema com um checkpoint
    And o agente planta "um filtro em .gitattributes" no workspace
    When um novo checkpoint é criado
    Then o checkpoint existe e nada plantado executou

  Scenario: Configuração plantada é ignorada
    Given um sistema com um checkpoint
    And o agente planta "um core.fsmonitor na config" no workspace
    When um novo checkpoint é criado
    Then o checkpoint existe e nada plantado executou

  Scenario: Arquivo restaurado continua editável
    Given um sistema com um checkpoint
    When o dono restaura esse checkpoint depois de o agente apagar o arquivo
    Then o arquivo restaurado pode ser alterado pelo agente

  Scenario: Checkpoint antigo continua restaurável
    Given um sistema anterior à mudança, com checkpoints no ".git" do workspace
    When o dono restaura o primeiro checkpoint registrado
    Then o workspace volta ao estado daquele checkpoint

  Scenario: Histórico do workspace adulterado não substitui o registrado
    Given um sistema anterior à mudança, com checkpoints no ".git" do workspace
    And o agente aponta a branch do ".git" antigo para um commit próprio
    When o portal opera o repositório pela primeira vez
    Then o ponto atual é o último checkpoint registrado pelo portal

  Scenario: Nada do histórico sobra após a exclusão
    Given um sistema com um checkpoint
    When um administrador exclui o sistema definitivamente
    Then o repositório git do sistema deixa de existir

  Scenario: Arquivamento preserva o repositório
    Given um sistema com um checkpoint
    When o dono arquiva o sistema
    Then o repositório git do sistema é preservado
