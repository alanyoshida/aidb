Feature: Checkpoints git por execução
  Como dono de um sistema
  Quero restaurar o código da app a um checkpoint anterior sem perder os posteriores
  Para voltar atrás e ainda poder retomar o que veio depois
  # Fonte: specs/agent-harness/spec.md, requirement "Checkpoints git por execução"
  # (cenários alterados pela change isolate-workspace-repository)

  Scenario: Checkpoint criado
    Given um sistema sem checkpoints
    When uma execução do agente termina com sucesso alterando a app
    Then um checkpoint com a descrição da alteração aparece no histórico do sistema

  Scenario: Rollback para checkpoint
    Given um sistema com os checkpoints "v1", "v2" e "v3"
    When o dono restaura o checkpoint "v1"
    Then o workspace volta ao estado do checkpoint "v1"

  Scenario: Rollback preserva checkpoints posteriores
    Given um sistema com os checkpoints "v1", "v2" e "v3"
    When o dono restaura o checkpoint "v1"
    Then os checkpoints "v2" e "v3" continuam no histórico
    And o checkpoint "v2" continua restaurável

  Scenario: Rollback registrado como checkpoint
    Given um sistema com os checkpoints "v1", "v2" e "v3"
    When o dono restaura o checkpoint "v1"
    Then aparece no histórico um checkpoint de restauração que identifica "v1"

  Scenario: Rollback para o estado atual
    Given um sistema com os checkpoints "v1", "v2" e "v3"
    When o dono restaura o checkpoint "v3"
    Then o portal informa que não havia nada a restaurar
    And nenhum checkpoint novo é criado
