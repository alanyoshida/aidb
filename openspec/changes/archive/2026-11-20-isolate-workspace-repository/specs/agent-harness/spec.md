# Spec Delta

## MODIFIED Requirements

### Requirement: Checkpoints git por execução
O portal SHALL criar um checkpoint git do workspace ao final de cada execução bem-sucedida, registrar seu histórico por sistema e permitir rollback para checkpoint anterior. O rollback SHALL preservar o histórico: os checkpoints posteriores ao restaurado continuam existindo e a restauração é registrada como um checkpoint novo.

#### Scenario: Checkpoint criado
- **WHEN** uma execução do agente termina com sucesso
- **THEN** um checkpoint com descrição da alteração aparece no histórico do sistema

#### Scenario: Rollback para checkpoint
- **WHEN** o dono restaura um checkpoint anterior
- **THEN** o workspace volta ao estado daquele checkpoint e a app é reiniciada nesse estado

#### Scenario: Rollback preserva checkpoints posteriores
- **WHEN** o dono restaura um checkpoint que não é o mais recente
- **THEN** os checkpoints criados depois dele continuam no histórico e continuam restauráveis

#### Scenario: Rollback registrado como checkpoint
- **WHEN** o dono restaura um checkpoint anterior
- **THEN** aparece no histórico um checkpoint novo identificando qual checkpoint foi restaurado

#### Scenario: Rollback para o estado atual
- **WHEN** o dono restaura um checkpoint cujo conteúdo é idêntico ao estado atual do workspace
- **THEN** o portal informa que não havia nada a restaurar e não cria checkpoint novo
